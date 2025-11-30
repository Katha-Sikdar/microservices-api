import http from 'k6/http';
import { check, sleep } from 'k6';

// Paste the long encoded token you copied from jwt.io here
const authToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyNDU2IiwibmFtZSI6IlRlc3QgVXNlciIsImlhdCI6MTc2MzQwNTUzNywiZXhwIjoxNzYzNDA5MTM3fQ.pdO7qYKak0WJseiD2w0n9xbf4G9LIYHh60KaNRZiDhk';

export const options = {
  insecureSkipTLSVerify: true, // Still needed for self-signed cert
  stages: [
    { duration: '20s', target: 100 },
    { duration: '1m', target: 100 },
    { duration: '10s', target: 0 },
  ],
};

export default function () {
  // Set up the request headers, including the Authorization token
  const params = {
    headers: {
      'Authorization': `Bearer ${authToken}`,
    },
  };

  // Send the request with the headers
  const res = http.get('https://localhost/products', params);
  check(res, { 'status was 200': (r) => r.status == 200 });
  sleep(1);
}