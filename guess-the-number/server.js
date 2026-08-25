const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = process.env.PORT || 3000;
const ROOT = __dirname;
const DATA_FILE = path.join(ROOT, 'data.json');
const WORDS_FILE = path.join(ROOT, 'words.json');
const CREATOR_USERNAME = (process.env.RANGEFINDER_CREATOR || 'creator').trim().toLowerCase();
const CREATOR_CODE = process.env.RANGEFINDER_CREATOR_CODE || 'daily-arcade-owner';
const WORDS = JSON.parse(fs.readFileSync(WORDS_FILE, 'utf8'));

function today() {
  return new Date().toISOString().slice(0, 10);
}

function readData() {
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  } catch {
    return { challenge: null, players: {} };
  }
}

function writeData(data) {
  fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
}

function getData() {
  const data = readData();
  if (!data.challenge || data.challenge.date !== today()) {
    data.challenge = { date: today(), target: crypto.randomInt(1, 101) };
    Object.values(data.players).forEach((player) => {
      player.daily = null;
    });
    writeData(data);
  }
  return data;
}

function getPlayerId(request, response) {
  const cookies = request.headers.cookie || '';
  const match = cookies.match(/rangefinder_player=([^;]+)/);
  if (match) return match[1];
  const id = crypto.randomUUID();
  response.setHeader('Set-Cookie', `rangefinder_player=${id}; Path=/; SameSite=Lax; Max-Age=31536000`);
  return id;
}

function leaderboard(data) {
  const scores = Object.values(data.players).flatMap((player) => {
    const daily = player.daily;
    if (!daily || daily.date !== today()) return [];
    return (daily.scores || (daily.completed ? [daily.moves] : [])).slice(0, 1).map((moves) => ({ name: player.name, moves }));
  });
  return scores.sort((a, b) => a.moves - b.moves || a.name.localeCompare(b.name))
    .slice(0, 100)
    .map((score, index) => ({ rank: index + 1, name: score.name, moves: score.moves }));
}

function higherLowerLeaderboard(data) {
  const scores = Object.values(data.players).flatMap((player) => {
    const game = player.higherLower;
    if (!game || game.date !== today()) return [];
    return (game.scores || (game.completed ? [game.score] : [])).slice(0, 1).map((score) => ({ name: player.name, score }));
  });
  return scores.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
    .slice(0, 100)
    .map((score, index) => ({ rank: index + 1, name: score.name, score: score.score }));
}

function wordLeaderboard(data) {
  const scores = Object.values(data.players).flatMap((player) => {
    const game = player.wordGame;
    if (!game || game.date !== today()) return [];
    return (game.scores || (game.completed ? [game.score] : [])).slice(0, 1).map((score) => ({ name: player.name, score }));
  });
  return scores.sort((a, b) => b.score - a.score || a.name.localeCompare(b.name))
    .slice(0, 100)
    .map((score, index) => ({ rank: index + 1, name: score.name, score: score.score }));
}

function newWordGame(scores = []) {
  return { date: today(), current: WORDS[Math.floor(Math.random() * WORDS.length)], seen: [], newSinceRepeat: 0, currentIsRepeat: false, history: [], score: 0, scores, completed: false };
}

function publicState(data, playerId) {
  const player = data.players[playerId];
  const daily = player && player.daily && player.daily.date === today() ? player.daily : null;
  return {
    date: today(),
    name: player ? player.name : '',
    moves: daily ? daily.moves : 0,
    guesses: daily ? daily.guesses : [],
    completed: Boolean(daily && daily.completed),
    isCreator: Boolean(player && (player.isCreator || ['creator', CREATOR_USERNAME].includes(player.name.toLowerCase()))),
    leaderboard: leaderboard(data),
    higherLower: publicHigherLowerState(data, playerId),
    wordGame: publicWordState(data, playerId)
  };
}

function publicHigherLowerState(data, playerId) {
  const player = data.players[playerId];
  const game = player && player.higherLower && player.higherLower.date === today() ? player.higherLower : null;
  return { current: game ? game.current : null, score: game ? game.score : 0, history: game ? game.history : [], completed: Boolean(game && game.completed), isCreator: Boolean(player && (player.isCreator || player.name.toLowerCase() === CREATOR_USERNAME)), leaderboard: higherLowerLeaderboard(data) };
}

function publicWordState(data, playerId) {
  const player = data.players[playerId];
  const game = player && player.wordGame && player.wordGame.date === today() ? player.wordGame : null;
  return { current: game ? game.current : null, score: game ? game.score : 0, history: [], lastResult: game && game.history.length ? game.history[game.history.length - 1] : null, completed: Boolean(game && game.completed), leaderboard: wordLeaderboard(data) };
}

function sendJson(response, status, body) {
  response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  response.end(JSON.stringify(body));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let body = '';
    request.on('data', (chunk) => { body += chunk; });
    request.on('end', () => {
      try { resolve(body ? JSON.parse(body) : {}); } catch { reject(new Error('Invalid JSON')); }
    });
    request.on('error', reject);
  });
}

const server = http.createServer(async (request, response) => {
  const playerId = getPlayerId(request, response);
  const data = getData();

  if (request.url === '/api/state' && request.method === 'GET') {
    const player = data.players[playerId];
    if (player && (!player.higherLower || player.higherLower.date !== today())) {
      player.higherLower = { date: today(), current: crypto.randomInt(1, 101), score: 0, history: [], completed: false };
      writeData(data);
    }
    if (player && (!player.wordGame || player.wordGame.date !== today())) {
      player.wordGame = newWordGame(player.wordGame ? player.wordGame.scores || [] : []);
      writeData(data);
    }
    return sendJson(response, 200, publicState(data, playerId));
  }

  if (request.url === '/api/profile' && request.method === 'POST') {
    try {
      const body = await readBody(request);
      const name = String(body.name || '').trim().slice(0, 18);
      if (!name) return sendJson(response, 400, { error: 'Choose a name first.' });
      const taken = Object.entries(data.players).some(([otherId, player]) => otherId !== playerId && player.name.toLowerCase() === name.toLowerCase());
      if (taken) return sendJson(response, 409, { error: 'That username is already taken.' });
      const player = data.players[playerId] = data.players[playerId] || { name, daily: null };
      if (['creator', CREATOR_USERNAME].includes(player.name.toLowerCase())) player.isCreator = true;
      if (body.creatorCode === CREATOR_CODE) player.isCreator = true;
      player.name = name;
      writeData(data);
      return sendJson(response, 200, publicState(data, playerId));
    } catch (error) {
      return sendJson(response, 400, { error: error.message });
    }
  }

  if (request.url === '/api/higher-lower' && request.method === 'POST') {
    try {
      const body = await readBody(request);
      const player = data.players[playerId];
      if (!player) return sendJson(response, 400, { error: 'Choose a name first.' });
      if (!player.higherLower || player.higherLower.date !== today()) player.higherLower = { date: today(), current: crypto.randomInt(1, 101), score: 0, history: [], scores: [], completed: false };
      const game = player.higherLower;
      if (game.completed) player.higherLower = { date: today(), current: crypto.randomInt(1, 101), score: 0, history: [], scores: game.scores || [], completed: false };
      const activeGame = player.higherLower;
      if (!['higher', 'lower'].includes(body.prediction)) return sendJson(response, 400, { error: 'Choose higher or lower.' });
      const next = crypto.randomInt(1, 101);
      const correct = body.prediction === 'higher' ? next > activeGame.current : next < activeGame.current;
      activeGame.history.push({ from: activeGame.current, to: next, prediction: body.prediction, correct });
      if (correct) { activeGame.score += 1; activeGame.current = next; } else { activeGame.completed = true; activeGame.scores = activeGame.scores || []; activeGame.scores.push(activeGame.score); }
      writeData(data);
      return sendJson(response, 200, { correct, next, state: publicHigherLowerState(data, playerId) });
    } catch (error) { return sendJson(response, 400, { error: error.message }); }
  }

  if (request.url === '/api/word-game' && request.method === 'POST') {
    try {
      const body = await readBody(request);
      const player = data.players[playerId];
      if (!player) return sendJson(response, 400, { error: 'Choose a name first.' });
      if (!player.wordGame || player.wordGame.date !== today()) player.wordGame = newWordGame();
      if (player.wordGame.completed) player.wordGame = newWordGame(player.wordGame.scores || []);
      const game = player.wordGame;
      if (!['new', 'seen'].includes(body.answer)) return sendJson(response, 400, { error: 'Choose new or already seen.' });
      const expected = game.currentIsRepeat ? 'seen' : 'new';
      const correct = body.answer === expected;
      const word = game.current;
      game.history.push({ word, answer: body.answer, correct });
      if (!game.seen.includes(word)) game.seen.push(word);
      if (correct) {
        game.score += 1;
        game.newSinceRepeat = game.currentIsRepeat ? 0 : game.newSinceRepeat + 1;
        if (game.newSinceRepeat >= 2) {
          game.current = game.seen[Math.floor(Math.random() * game.seen.length)];
          game.currentIsRepeat = true;
        } else {
          const unseen = WORDS.filter((candidate) => !game.seen.includes(candidate));
          game.current = (unseen.length ? unseen : WORDS)[Math.floor(Math.random() * (unseen.length ? unseen.length : WORDS.length))];
          game.currentIsRepeat = false;
        }
      } else {
        game.completed = true;
        if (!game.scores.length) game.scores.push(game.score);
      }
      writeData(data);
      return sendJson(response, 200, { correct, state: publicWordState(data, playerId) });
    } catch (error) { return sendJson(response, 400, { error: error.message }); }
  }

  if (request.url === '/api/word-game/retry' && request.method === 'POST') {
    const player = data.players[playerId];
    if (!player) return sendJson(response, 400, { error: 'Choose a name first.' });
    const game = player.wordGame;
    if (!game || game.date !== today() || !game.completed) return sendJson(response, 400, { error: 'Finish the current round before retrying.' });
    player.wordGame = newWordGame(game.scores || []);
    writeData(data);
    return sendJson(response, 200, publicWordState(data, playerId));
  }

  if (request.url === '/api/higher-lower/retry' && request.method === 'POST') {
    const player = data.players[playerId];
    if (!player) return sendJson(response, 400, { error: 'Choose a name first.' });
    const game = player.higherLower;
    if (!game || game.date !== today() || !game.completed) return sendJson(response, 400, { error: 'Finish the current chain before retrying.' });
    player.higherLower = { date: today(), current: crypto.randomInt(1, 101), score: 0, history: [], scores: game.scores || [], completed: false };
    writeData(data);
    return sendJson(response, 200, publicHigherLowerState(data, playerId));
  }

  if (request.url === '/api/guess' && request.method === 'POST') {
    try {
      const body = await readBody(request);
      const guess = Number(body.guess);
      if (!Number.isInteger(guess) || guess < 1 || guess > 100) {
        return sendJson(response, 400, { error: 'Enter a whole number from 1 to 100.' });
      }
      const player = data.players[playerId];
      if (!player) return sendJson(response, 400, { error: 'Choose a name first.' });
      if (!player.daily || player.daily.date !== today()) {
        player.daily = { date: today(), moves: 0, guesses: [], completed: false };
      }
      if (player.daily.completed) player.daily = { date: today(), moves: 0, guesses: [], scores: player.daily.scores || [], completed: false };
      player.daily.moves += 1;
      const correct = guess === data.challenge.target;
      const hint = correct ? 'Correct' : guess < data.challenge.target ? 'Go higher' : 'Go lower';
      player.daily.guesses.push({ value: guess, hint });
      player.daily.completed = correct;
      if (correct && !(player.daily.scores || []).length) {
        player.daily.scores = player.daily.scores || [];
        player.daily.scores.push(player.daily.moves);
      }
      writeData(data);
      return sendJson(response, 200, { correct, hint, state: publicState(data, playerId) });
    } catch (error) {
      return sendJson(response, 400, { error: error.message });
    }
  }

  const staticFiles = {
    '/': ['index.html', 'text/html; charset=utf-8'],
    '/index.html': ['index.html', 'text/html; charset=utf-8'],
    '/manifest.json': ['manifest.json', 'application/manifest+json'],
    '/icon.svg': ['icon.svg', 'image/svg+xml'],
    '/sw.js': ['sw.js', 'application/javascript'],
    '/robots.txt': ['robots.txt', 'text/plain; charset=utf-8']
  };
  const staticFile = staticFiles[new URL(request.url, 'http://localhost').pathname];
  if (staticFile) {
    response.writeHead(200, { 'Content-Type': staticFile[1] });
    return fs.createReadStream(path.join(ROOT, staticFile[0])).pipe(response);
  }

  response.writeHead(404);
  response.end('Not found');
});

server.listen(PORT, () => {
  console.log(`Daily Arcade is running at http://localhost:${PORT}`);
});
