// const express = require('express');
// const app = express();
// const port = 3000;

// const products = [
//   { id: 1, name: 'Laptop' },
//   { id: 2, name: 'Keyboard' },
//   { id: 3, name: 'Mouse' }
// ];

// app.get('/products', (req, res) => {
//   res.json(products);
// });

// app.listen(port, () => {
//   console.log(`service-a listening at http://localhost:${port}`);
// });

// for tls+jwt

const express = require('express');
const jwt = require('jsonwebtoken'); // Import the library
const app = express();
const port = 3000;

// This secret key MUST match the one you use to create the token
const JWT_SECRET = 'your-super-secret-key-that-is-long';

const products = [
  { id: 1, name: 'Laptop' },
  { id: 2, name: 'Keyboard' },
  { id: 3, name: 'Mouse' }
];

app.get('/products', (req, res) => {
  // --- Start of JWT Validation Logic ---
  const authHeader = req.headers['authorization'];
  const token = authHeader && authHeader.split(' ')[1]; // Format is "Bearer TOKEN"

  if (token == null) {
    return res.sendStatus(401); // 401 Unauthorized if no token is present
  }

  // Verify the token's signature against the secret key
  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) {
      return res.sendStatus(403); // 403 Forbidden if token is invalid or expired
    }
    // If the token is valid, proceed to return the data
    res.json(products);
  });
  // --- End of JWT Validation Logic ---
});

app.listen(port, () => {
  console.log(`service-a (with JWT check) listening at http://localhost:${port}`);
});