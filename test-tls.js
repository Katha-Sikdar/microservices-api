import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  // Ramping up VUs (Virtual Users) can be more realistic
  stages: [
    { duration: '20s', target: 100 }, // Ramp-up to 100 users over 20 seconds
    { duration: '1m', target: 100 },  // Stay at 100 users for 1 minute
    { duration: '10s', target: 0 },   // Ramp-down to 0 users
  ],
};

export default function () {
  //const res = http.get('http://localhost/products'); For Baseline
  const res = http.get('https://localhost/products');
  check(res, { 'status was 200': (r) => r.status == 200 });
  sleep(1);
}