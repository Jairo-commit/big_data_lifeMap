"""Entrega 2, punto 8: estado de Kafka y retraso de los consumidores para /health.

El estado se calcula en un hilo de fondo y /health solo lee la última foto: así la respuesta es instantánea aunque el
broker esté caído (el healthcheck de Docker espera 3 s y no debe fallar por culpa de Kafka).

- Estado del broker y offsets finales por partición del topic: kafka-python (`probe_kafka`).
- Retraso de cada consumidor = offset final - siguiente offset a procesar (live.lag_by_partition). Los consumidores son
  los jobs de streaming: `streaming_alerts` deja su avance en `stream_progress` y `streaming_inference` en
  `review_predictions` (máximo `kafka_offset` por partición).

Sin KAFKA_BOOTSTRAP (staging) el estado es "not_configured" y no cuenta como fallo.
"""

import logging
import threading
import time

from live import lag_by_partition

log = logging.getLogger("lifemap-api.kafka")


def probe_kafka(bootstrap, topic, timeout_ms=3000):
    """Offsets finales por partición {"0": n, ...} del topic; lanza una excepción si el broker no responde."""
    from kafka import KafkaConsumer, TopicPartition

    consumer = KafkaConsumer(
        bootstrap_servers=bootstrap,
        api_version=(2, 6, 0),  # evita sondear la versión del broker en cada conexión
        group_id=None,
        request_timeout_ms=timeout_ms + 2000,
        session_timeout_ms=timeout_ms,
        heartbeat_interval_ms=timeout_ms // 3,
        consumer_timeout_ms=timeout_ms,
        metadata_max_age_ms=timeout_ms,
    )
    try:
        partitions = consumer.partitions_for_topic(topic)
        if not partitions:
            raise RuntimeError(f"el topic '{topic}' no existe o el broker no respondió")
        topic_partitions = [TopicPartition(topic, p) for p in sorted(partitions)]
        return {str(tp.partition): offset for tp, offset in consumer.end_offsets(topic_partitions).items()}
    finally:
        consumer.close()


class KafkaMonitor:
    """Foto periódica del estado de Kafka: broker, offsets finales y retraso de cada consumidor."""

    def __init__(
        self,
        bootstrap,
        topic,
        probe,
        progress_reader,
        interval=10.0,
        stale_after=60.0,
        probe_timeout=8.0,
        clock=time.monotonic,
    ):
        self.bootstrap = bootstrap
        self.topic = topic
        self.probe = probe
        self.progress_reader = progress_reader  # () -> {consumidor: {partición: siguiente offset}}
        self.interval = interval
        self.stale_after = stale_after
        self.probe_timeout = probe_timeout
        self.clock = clock
        self._probe_thread = None
        self._lock = threading.Lock()
        self._state = None
        self._checked_at = None

    @property
    def configured(self):
        return bool(self.bootstrap)

    def _probe_with_deadline(self):
        """Ejecuta el sondeo con un plazo duro: kafka-python reintenta la conexión sin límite si el broker está caído.

        El sondeo corre en su propio hilo; si no termina en `probe_timeout` segundos se da por caído. Mientras un sondeo
        anterior siga colgado no se lanza otro, para no acumular hilos y sockets.
        """
        if self._probe_thread is not None and self._probe_thread.is_alive():
            raise TimeoutError(f"el sondeo anterior de Kafka sigue sin responder (más de {self.probe_timeout:g} s)")
        result = {}

        def run():
            try:
                result["value"] = self.probe(self.bootstrap, self.topic)
            except Exception as error:
                result["error"] = error

        thread = threading.Thread(target=run, name="kafka-probe", daemon=True)
        self._probe_thread = thread
        thread.start()
        thread.join(self.probe_timeout)
        if thread.is_alive():
            raise TimeoutError(f"Kafka no respondió en {self.probe_timeout:g} s")
        if "error" in result:
            raise result["error"]
        return result["value"]

    def refresh(self):
        """Sondea Kafka y guarda la foto; un fallo queda registrado como 'unreachable', nunca se propaga."""
        try:
            end_offsets = self._probe_with_deadline()
            state = {"status": "healthy", "topic": self.topic, "end_offsets": end_offsets, "consumers": {}}
            try:
                progress = self.progress_reader() or {}
            except Exception as error:
                log.warning("No se pudo leer el avance de los consumidores: %s", error)
                progress = {}
            for name, next_offsets in progress.items():
                lag = lag_by_partition(end_offsets, next_offsets)
                state["consumers"][name] = lag if lag is not None else {"status": "unknown"}
        except Exception as error:
            state = {"status": f"unreachable: {error}", "topic": self.topic, "end_offsets": {}, "consumers": {}}
        with self._lock:
            self._state, self._checked_at = state, self.clock()

    def snapshot(self):
        """Última foto, sin esperar a Kafka: not_configured, unknown (aún no sondeado), stale (hilo atascado) o la real."""
        if not self.configured:
            return {"status": "not_configured"}
        with self._lock:
            state, checked_at = self._state, self._checked_at
        if state is None:
            return {"status": "unknown", "topic": self.topic}
        if self.clock() - checked_at > self.stale_after:
            return dict(state, status="stale")
        return state

    def start(self):
        """Arranca el hilo de fondo (daemon); no hace nada si Kafka no está configurado."""
        if not self.configured:
            return None

        def loop():
            while True:
                self.refresh()
                time.sleep(self.interval)

        thread = threading.Thread(target=loop, name="kafka-monitor", daemon=True)
        thread.start()
        return thread
