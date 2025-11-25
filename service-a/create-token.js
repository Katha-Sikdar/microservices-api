// create-token.js
const jwt = require('jsonwebtoken');

// 1. Define the Payload (the user data)
const payload = {
  sub: 'user456',
  name: 'Test User',
  // You can add any other data you want here
};

// 2. Define the Secret Key (MUST MATCH THE SERVER'S SECRET)
const secretKey = 'your-super-secret-key-that-is-long';

// 3. Define Token Options (e.g., how long it's valid)
const options = {
  expiresIn: '1h' // This token will be valid for one hour
};

// 4. Create the token
const token = jwt.sign(payload, secretKey, options);

// 5. Print it to the console
console.log('Your JWT for testing is:');
console.log(token);