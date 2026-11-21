/** Ciudades con más negocios en el dataset. Las coordenadas son el centro de cada ciudad. */
export interface City {
  name: string;
  state: string;
  lat: number;
  lon: number;
  businesses: number;
}

export const CITIES: City[] = [
  { name: "Philadelphia", state: "PA", lat: 39.9526, lon: -75.1652, businesses: 14569 },
  { name: "Tucson", state: "AZ", lat: 32.2226, lon: -110.9747, businesses: 9250 },
  { name: "Tampa", state: "FL", lat: 27.9506, lon: -82.4572, businesses: 9050 },
  { name: "Indianapolis", state: "IN", lat: 39.7684, lon: -86.1581, businesses: 7540 },
  { name: "Nashville", state: "TN", lat: 36.1627, lon: -86.7816, businesses: 6971 },
  { name: "New Orleans", state: "LA", lat: 29.9511, lon: -90.0715, businesses: 6209 },
  { name: "Reno", state: "NV", lat: 39.5296, lon: -119.8138, businesses: 5935 },
  { name: "Edmonton", state: "AB", lat: 53.5461, lon: -113.4938, businesses: 5054 },
  { name: "Saint Louis", state: "MO", lat: 38.627, lon: -90.1994, businesses: 4827 },
];

export const DEFAULT_CITY = CITIES[0] as City;
