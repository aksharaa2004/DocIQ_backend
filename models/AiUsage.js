const mongoose = require("mongoose");

const AiUsageSchema = new mongoose.Schema(
  {
    operation: { type: String, required: true, index: true },
    userId: { type: mongoose.Schema.Types.ObjectId, ref: "User", default: null, index: true },
    path: { type: String, required: true },
    statusCode: { type: Number, required: true },
  },
  { timestamps: true }
);

module.exports = mongoose.model("AiUsage", AiUsageSchema);
