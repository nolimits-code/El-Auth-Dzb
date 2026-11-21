const express = require("express");
const cors = require("cors");
const fs = require("fs");
const path = require("path");

const app = express();
const PORT = process.env.PORT || 5000;
const ADMIN_KEY = process.env.ADMIN_KEY || "ADMIN-2026";
const DB_FILE = path.join(__dirname, "keys.json");

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

function loadKeys() {
  if (!fs.existsSync(DB_FILE)) {
    fs.writeFileSync(DB_FILE, JSON.stringify({}, null, 2));
  }
  return JSON.parse(fs.readFileSync(DB_FILE, "utf8"));
}

function saveKeys(data) {
  fs.writeFileSync(DB_FILE, JSON.stringify(data, null, 2));
}

function authAdmin(req, res, next) {
  const header = req.headers.authorization || "";
  const token = header.replace(/^Bearer\s+/i, "").trim();
  if (!token || token !== ADMIN_KEY) {
    return res.status(401).json({ success: false, message: "Unauthorized" });
  }
  next();
}

function makeKey(prefix) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let rnd = "";
  for (let i = 0; i < 6; i++) rnd += chars[Math.floor(Math.random() * chars.length)];
  return `${prefix || "NoLimite"}-${rnd}`;
}

app.get("/api/keys", authAdmin, (req, res) => {
  res.json({ success: true, keys: loadKeys() });
});

app.post("/api/keys/create", authAdmin, (req, res) => {
  const db = loadKeys();
  const count = Math.min(Math.max(parseInt(req.body.count, 10) || 1, 1), 50);
  const duration = req.body.duration || "30d";
  const max_uses = req.body.max_uses || "Global";
  const prefix = req.body.prefix || "NoLimite";

  const created = [];
  for (let i = 0; i < count; i++) {
    const key = makeKey(prefix);
    db[key] = {
      duration,
      max_uses,
      hwid_list: [],
      created_at: new Date().toISOString()
    };
    created.push(key);
  }
  saveKeys(db);
  res.json({ success: true, keys: created });
});

app.get("/verify", (req, res) => {
  const key = (req.query.key || "").trim();
  const hwid = (req.query.hwid || "").trim();
  const db = loadKeys();

  if (!key || !db[key]) {
    return res.json({ success: false, message: "Invalid key" });
  }

  const entry = db[key];
  const isGlobal =
    String(entry.max_uses).toLowerCase() === "global" ||
    String(entry.max_uses).toLowerCase() === "unlimited";

  if (!isGlobal && hwid) {
    if (!entry.hwid_list.includes(hwid)) {
      const limitNum = parseInt(entry.max_uses, 10) || 1;
      if (entry.hwid_list.length >= limitNum) {
        return res.json({ success: false, message: "HWID limit reached" });
      }
      entry.hwid_list.push(hwid);
      saveKeys(db);
    }
  }

  return res.json({
    success: true,
    key,
    hwid,
    expiry: entry.duration || "Lifetime",
    max_uses: entry.max_uses || "Global",
    message: "Key valid"
  });
});

app.listen(PORT, () => {
  console.log(`Auth API running on port ${PORT}`);
});