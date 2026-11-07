# CI/CD with Jenkins

Jenkins tests every pull request into `main`. Every change that reaches `main` (a merged pull
request or a push) is tested, built into Docker images, started, checked through the API and
deployed on this PC.

| Event | Job | Stages |
|---|---|---|
| Pull request into `main` (opened, or new commits) | `PR-<number>` | Install → Lint → Test |
| Change that reaches `main` | `main` | Install → Lint → Test → Build images → Start services → API tests → Deploy |

Stages run in order and the build stops at the first failure. **If any test fails, nothing is
deployed.** Pushes to other branches build nothing.

**Builds start within seconds:** GitHub sends a webhook to Jenkins on every push and pull
request, through an [ngrok](https://ngrok.com/) tunnel. A scan every hour only catches what a
missed webhook skipped (for example while this PC was off).

```
 PR opened / merged into main
            │
            ▼
         GitHub ── webhook ──► ngrok (public HTTPS URL) ──► Jenkins (container on this PC, :8095)
            ▲                                                   │
            └──────────── ✓ / ✗ on the commit ──────────────────┤
                                                                ▼
                                             Jenkinsfile: CI on every build, CD on main only
```

## What turns each stage on (for the team)

The project is still being built, so the [`Jenkinsfile`](../Jenkinsfile) runs each group of
stages only when the files it needs exist. Until then they show as *skipped* and the build is
green. **Nobody needs to edit the `Jenkinsfile` to switch them on**: adding the files is enough.

| Group | Switches on when these exist | What each file must provide |
|---|---|---|
| **CI** (Install, Lint, Test) | `pyproject.toml` | `uv.lock` committed (`uv lock`), and `ruff` and `pytest` as dev dependencies (`uv add --dev ruff pytest`). Tests in `tests/`. While there are none, *Test* passes with "No tests found yet". |
| **CD** (Build images, Start services, API tests, Deploy) | all three: `docker-compose.yml`, `jenkins/docker-compose.staging.yml`, `jenkins/api-tests.sh` | See below. CD needs all three, so the stack is never deployed without its API tests. |

For CD:

- **`docker-compose.yml`**: the whole system. Give the API (and anything the others wait for) a
  `healthcheck`: *Start services* waits until they are healthy. Do not use `8095` as a host port
  (Jenkins), and do not set `container_name`: staging and the deployed stack run side by side.
- **`jenkins/docker-compose.staging.yml`**: removes the published ports, so staging can run
  next to the deployed stack. One entry per service that publishes ports:

  ```yaml
  services:
    api:
      ports: !reset []
  ```

- **`jenkins/api-tests.sh`** (executable, `chmod +x`): calls the staging API and exits with 1 if
  a check fails. It gets the API URL as its first argument. The `Jenkinsfile` passes
  `http://api:5000`; change that line if the service or port is different. Each check is a
  `curl` call whose JSON response is checked with `jq`.
- **Secrets** (API tokens, passwords): never in the repository. Add them as Jenkins credentials
  and wrap the `sh` of *Start services* and *Deploy* in `withCredentials([...]) { }`, for example
  `withCredentials([string(credentialsId: 'my-token', variable: 'MY_TOKEN')]) { sh '...' }`.
- **Kaggle** (credential `kaggle`, *Username with password*: Kaggle username + API key): the
  *Build images*, *Deploy* and *Ingest* stages expose it as `KAGGLE_USERNAME`/`KAGGLE_KEY`.
  `docker compose build dataset` downloads the ~5.5 GB Yelp files (business and review) into the image (a BuildKit
  secret, so the token is not stored); the layer is cached, so it happens once. The staging stack
  does not run `dataset` or `ingest`.
- If several services build the **same image**, change *Build images* to build one service per
  image (`docker compose build <service> <service>`): parallel builds of one image collide.

The pipeline assumes a Python project managed with `uv`. If the stack changes, change the three
CI commands.

| | Compose project | Ports on this PC |
|---|---|---|
| Staging | `lifemap-staging` | none. Started in each `main` build for the API tests, then removed. |
| Deployed | `lifemap` | the ones in `docker-compose.yml`. Updated only when every test passed. |

## Setup (repository owner, once)

### A. Jenkins

Jenkins runs as a container on this PC, built from [`jenkins/Dockerfile`](Dockerfile) (uv, the
Docker CLI with compose, and jq). It has no Docker daemon inside: it uses the host's Docker through
its socket, so the socket must be mounted and the `jenkins` user must be in the socket's group.

```bash
docker build -t lifemap-jenkins jenkins/
docker run -d --name jenkins --restart unless-stopped \
  -p 8095:8080 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --group-add "$(stat -c %g /var/run/docker.sock)" \
  lifemap-jenkins
```

- `--restart unless-stopped` starts it again when the PC boots.
- The first admin password: `docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword`.
  Open `http://localhost:8095`, install the suggested plugins, and also **GitHub Branch Source**.
- Check that it reaches Docker: `docker exec jenkins docker ps` must list the containers.

### B. The job

1. **GitHub token**: from an account with write access to this repository, create
   one (**GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**)
   and add it in Jenkins as *Username with password* (username + token).
2. **New Item** → `big-data-lifemap` → **Multibranch Pipeline** → OK. Then:
   - **Branch Sources → Add source → GitHub**:
     - **Credentials**: the token.
     - **Repository HTTPS URL**: `https://github.com/Jairo-commit/big_data_lifeMap.git` → **Validate**.
     - **Behaviours**:
       - *Discover branches*, strategy *All branches*.
       - *Discover pull requests from origin*, strategy *Merging the pull request with the
         current target branch revision*.
       - *Discover pull requests from forks*, same strategy, trust *From users with Admin or
         Write permission*.
       - **Add → Filter by name (with wildcards)**: **Include** `main PR-*`.
   - **Build Configuration**: *by Jenkinsfile*, **Script Path**: `Jenkinsfile`.
   - **Scan Repository Triggers**: **Periodically if not otherwise run**, *1 hour* (only a
     fallback; the webhook starts the builds).
3. Save. The scan log lists `main` once the `Jenkinsfile` is on `main`.

### C. ngrok

GitHub must reach Jenkins, but `localhost:8095` only exists on this PC. ngrok gives it a public
HTTPS address and forwards the requests through a tunnel.

1. Create a free account at [ngrok.com](https://ngrok.com/). On the dashboard copy your
   **authtoken**, and under **Domains** claim the free **static domain**
   (e.g. `something.ngrok-free.app`). The static domain keeps the URL the same after every
   restart, so the webhook never has to be edited.
2. Run ngrok as a container that Docker starts again when the PC boots, like Jenkins:

   ```bash
   docker run -d --name ngrok --restart unless-stopped --network host \
     -e NGROK_AUTHTOKEN=<your authtoken> \
     ngrok/ngrok:latest http --url=<your static domain> 8095
   ```

   `--network host` lets it reach `localhost:8095`. Check it with `docker logs ngrok` and by
   opening `https://<your static domain>` (ngrok's free plan shows a warning page in browsers
   first; webhooks are not affected).
3. **Jenkins is now on the internet.** In **Manage Jenkins → Security**, make sure anonymous
   users have no access and *Allow users to sign up* is off.
4. In **Manage Jenkins → System → Jenkins URL**: `https://<your static domain>/`. The ✓/✗ on
   GitHub then link to a page teammates can open. Use this address from now on, also on this PC
   (mixing it with `localhost:8095` gives *No valid crumb* errors).

### D. The webhook

1. **Secret** (so only GitHub can trigger builds): generate one with `openssl rand -hex 32`.
   In Jenkins, **Manage Jenkins → Credentials → Global → Add Credentials**: kind *Secret text*,
   **Secret**: the value, **ID**: `github-webhook-secret`. Then **Manage Jenkins → System →
   GitHub → Advanced → Shared secrets → Add** and select it.
2. On GitHub, **big_data_lifeMap → Settings → Webhooks → Add webhook**:
   - **Payload URL**: `https://<your static domain>/github-webhook/` (the trailing `/` is required)
   - **Content type**: `application/json`
   - **Secret**: the same value.
   - **Which events**: *Let me select individual events* → **Pushes** and **Pull requests** only.
   - **Active** → **Add webhook**. The ping under **Recent Deliveries** should show a ✓.

### E. Block merging when the build fails (optional)

Once Jenkins has posted a ✓/✗ on a pull request, **Settings → Branches → Add branch protection
rule** for `main`: ✅ *Require a pull request before merging*, ✅ *Require status checks to pass*
→ add `continuous-integration/jenkins/pr-merge`.

### F. Check it

1. Push the branch with this `Jenkinsfile` and open a pull request into `main`. Within seconds
   `PR-<number>` builds. With no `pyproject.toml` yet, CI and CD show as skipped and the build
   is green.
2. Merge it. Within seconds the `main` build starts, and **Recent Deliveries** on GitHub shows
   the `push` event with a ✓.

## Troubleshooting

- **No build after a push or a pull request**: look at the delivery in GitHub's **Recent
  Deliveries**. Red ✗: ngrok is down (`docker ps`, `docker logs ngrok`) or the Payload URL lacks
  the trailing `/`. Green ✓ but no build: check the Behaviours and the filter `main PR-*` (B2),
  and click **Scan Repository Now**.
- **Delivery answers 4xx about the signature**: the secret on GitHub and in Jenkins differ (D).
- **PC was off**: GitHub does not retry; the hourly scan catches up, or click **Scan Repository
  Now**, or **Redeliver** from **Recent Deliveries**.
- **Deploy fails with `port is already allocated`**: a port in `docker-compose.yml` is already
  used by another container or program on this PC. `docker ps` shows who has it.
- **`failed to connect to the docker API at unix:///var/run/docker.sock`**: the Jenkins container
  was started without the Docker socket or without its group (`-v /var/run/docker.sock:...` and
  `--group-add`, section A).
- **Install fails with `The lockfile at uv.lock needs to be updated`**: run `uv lock` and commit
  `uv.lock`.
- **`Failed to spawn: ruff` / `pytest`**: add them with `uv add --dev ruff pytest`.
- **A CI stage fails**: run the same command locally (`uv sync --locked`, `uv run ruff check .`,
  `uv run pytest`).
