import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// Point this at your laptop's local network IP while developing on the
// same WiFi (no ngrok needed), or your Cloud Run URL in prod.
// Kept as a separate constant so it's a one-line change (or wire to app config / env).
export const API_BASE_URL = 'http://192.168.0.2:8001';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000,
});

// Attach the stored JWT to every request once the user is logged in
// (works for both rider and driver sessions — same token key).
apiClient.interceptors.request.use(async (config) => {
  const token = await AsyncStorage.getItem('itrola_access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// --- Auth ---
export const requestOtp = (phone) => apiClient.post('/auth/request-otp', { phone });

export const verifyOtp = (phone, otp, role = 'rider') =>
  apiClient.post('/auth/verify-otp', { phone, otp, role });

// --- Trips (rider side) ---
export const requestTrip = ({ pickup_lat, pickup_lng, dropoff_lat, dropoff_lng }) =>
  apiClient.post('/trips/request', { pickup_lat, pickup_lng, dropoff_lat, dropoff_lng });

export const getTrip = (tripId) => apiClient.get(`/trips/${tripId}`);

export const cancelTrip = (tripId) => apiClient.post(`/trips/${tripId}/cancel`);

// --- Payments ---
export const payForTrip = (tripId, momo_number, network) =>
  apiClient.post(`/trips/${tripId}/pay`, { momo_number, network });

// --- Trips (driver side) ---
// Requires the /trips/mine/current backend addition — see BACKEND_PATCH.md
export const getCurrentDriverTrip = () => apiClient.get('/trips/mine/current');

export const startTrip = (tripId) => apiClient.post(`/trips/${tripId}/start`);

export const completeTrip = (tripId) => apiClient.post(`/trips/${tripId}/complete`);

// --- Driver ---
export const updateDriverLocation = (driverId, lat, lng, heading) =>
  apiClient.post(`/drivers/${driverId}/location`, { lat, lng, heading });

// NOTE: `available` is a plain bool param on the backend (not a JSON body
// field), so FastAPI reads it as a query parameter — it must go in the URL.
export const setDriverAvailability = (driverId, available) =>
  apiClient.post(`/drivers/${driverId}/availability?available=${available}`);

export default apiClient;
