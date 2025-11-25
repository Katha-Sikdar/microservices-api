const express = require('express');
const app = express();
const port = 3001;

const reviews = [
  { id: 1, productId: 1, rating: 5, comment: 'Excellent!' },
  { id: 2, productId: 1, rating: 4, comment: 'Good value.' },
  { id: 3, productId: 2, rating: 5, comment: 'The best keyboard ever.' }
];

app.get('/reviews', (req, res) => {
  res.json(reviews);
});

app.listen(port, () => {
  console.log(`service-b listening at http://localhost:${port}`);
});