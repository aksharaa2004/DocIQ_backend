const crypto = require("crypto");
const jwt = require("jsonwebtoken");
const bcrypt = require("bcryptjs");
const User = require("../models/User");

const JWT_SECRET = process.env.JWT_SECRET || crypto.randomBytes(64).toString("hex");
const DEVELOPMENT_ADMIN_EMAIL = "admin@gmail.com";
const PREVIOUS_DEVELOPMENT_ADMIN_PASSWORD = "DocIQAdmin#2026";
const DEVELOPMENT_ADMIN_PASSWORD = "admin@1234";

if (!process.env.JWT_SECRET) {
  console.warn("JWT_SECRET is not configured; login tokens will expire when the server restarts.");
}
if (process.env.NODE_ENV === "production" && !process.env.JWT_SECRET) {
  throw new Error("Set JWT_SECRET before running DocIQ in production.");
}

function createAuthToken(user) {
  return jwt.sign({ sub: String(user._id) }, JWT_SECRET, { expiresIn: "12h" });
}

async function authenticateUser(req, res, next) {
  const authorization = req.get("authorization") || "";
  const [scheme, token] = authorization.split(" ");
  if (scheme !== "Bearer" || !token) {
    return res.status(401).json({ message: "Please sign in to continue." });
  }

  try {
    const payload = jwt.verify(token, JWT_SECRET);
    const user = await User.findById(payload.sub).select("name email role isActive");
    if (!user || !user.isActive) {
      return res.status(401).json({ message: "This account is inactive or no longer exists." });
    }
    req.user = user;
    return next();
  } catch {
    return res.status(401).json({ message: "Your session has expired. Please sign in again." });
  }
}

function requireAdmin(req, res, next) {
  if (req.user?.role !== "admin") {
    return res.status(403).json({ message: "Administrator access is required." });
  }
  return next();
}

async function bootstrapAdminAccount() {
  const configuredEmail = process.env.ADMIN_EMAIL?.trim().toLowerCase();
  const configuredPassword = process.env.ADMIN_PASSWORD;
  const isProduction = process.env.NODE_ENV === "production";

  if (isProduction && (!configuredEmail || !configuredPassword)) {
    console.warn("Admin bootstrap skipped in production. Set ADMIN_EMAIL and ADMIN_PASSWORD.");
    return;
  }

  const email = configuredEmail || DEVELOPMENT_ADMIN_EMAIL;
  const password = configuredPassword || DEVELOPMENT_ADMIN_PASSWORD;
  let admin = await User.findOne({ email });

  if (!admin) {
    admin = new User({
      name: "DocIQ Admin",
      email,
      password: await bcrypt.hash(password, 12),
      role: "admin",
      isActive: true,
    });
    await admin.save();
    console.log(`Initial admin account created for ${email}`);
    return;
  }

  if (
    (!configuredEmail || configuredEmail === DEVELOPMENT_ADMIN_EMAIL) &&
    (!configuredPassword || configuredPassword === PREVIOUS_DEVELOPMENT_ADMIN_PASSWORD) &&
    admin.email === DEVELOPMENT_ADMIN_EMAIL &&
    await bcrypt.compare(PREVIOUS_DEVELOPMENT_ADMIN_PASSWORD, admin.password)
  ) {
    admin.password = await bcrypt.hash(DEVELOPMENT_ADMIN_PASSWORD, 12);
    admin.role = "admin";
    await admin.save();
  }

  if (configuredEmail && admin.role !== "admin") {
    admin.role = "admin";
    await admin.save();
  } else if (!configuredEmail && admin.role !== "admin") {
    console.warn("Default admin email already belongs to a non-admin account; it was not promoted automatically.");
  }
}

module.exports = { JWT_SECRET, createAuthToken, authenticateUser, requireAdmin, bootstrapAdminAccount };
