// Optional zero-dependency static server (Node built-in http only).
// Alternative to `python3 -m http.server`. Serves index.html + data/*.json
// from the repo root so the dashboard can fetch its JSON same-origin.
//
//   node server.js           # serves on http://localhost:8000
//   PORT=3000 node server.js

const http = require("http");
const fs = require("fs");
const path = require("path");

const ROOT = __dirname;
const PORT = process.env.PORT || 8000;
const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
};

const server = http.createServer((req, res) => {
  let urlPath = decodeURIComponent(req.url.split("?")[0]);
  if (urlPath === "/") urlPath = "/index.html";

  // Resolve safely inside ROOT to prevent path traversal.
  const filePath = path.normalize(path.join(ROOT, urlPath));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403).end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { "Content-Type": "text/plain" }).end("Not found");
      return;
    }
    const type = TYPES[path.extname(filePath)] || "application/octet-stream";
    // No-cache so live.json / snapshot.json always refresh.
    res.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store" });
    res.end(data);
  });
});

server.listen(PORT, () => {
  console.log(`NBA Mood Mirror served at http://localhost:${PORT}/`);
});
