const mongoose = require("mongoose");

const DocumentSchema = new mongoose.Schema(
  {
    ownerId: {
      type: mongoose.Schema.Types.ObjectId,
      ref: "User",
      default: null,
      index: true,
    },

    originalName: {
      type: String,
      required: true,
    },

    fileName: {
      type: String,
      required: true,
    },

    filePath: {
      type: String,
      default: "",
    },

    fileUrl: {
      type: String,
      default: "",
    },

    cloudinaryPublicId: {
      type: String,
      default: "",
    },

    cloudinaryResourceType: {
      type: String,
      default: "raw",
    },

    fileType: {
      type: String,
      required: true,
    },

    fileSize: {
      type: Number,
      required: true,
    },

    contentHash: {
      type: String,
      default: "",
      index: true,
    },

    status: {
      type: String,
      enum: ["processing", "ready", "failed"],
      default: "processing",
    },

    processingError: {
      type: String,
      default: "",
    },

    // Stores the last time the user opened this document
    lastOpenedAt: {
      type: Date,
      default: null,
    },

    // Extracted document pages
    pages: [
      {
        pageNumber: {
          type: Number,
        },

        text: {
          type: String,
        },
      },
    ],

    // Saved bookmarks
    bookmarks: [
      {
        pageNumber: {
          type: Number,
          required: true,
        },
      },
    ],

    // Saved text highlights
    highlights: [
      {
        id: {
          type: String,
          required: true,
        },

        pageNumber: {
          type: Number,
          required: true,
        },

        text: {
          type: String,
          required: true,
        },

        /*
         * Exact character positions inside the page text.
         *
         * These allow DocIQ to restore the exact selected
         * occurrence even when the same text appears multiple
         * times on the same page.
         *
         * They are optional so older highlights created before
         * this update continue to work.
         */
        start: {
          type: Number,
          default: null,
        },

        end: {
          type: Number,
          default: null,
        },

        createdAt: {
          type: Date,
          default: Date.now,
        },
      },
    ],
  },
  {
    timestamps: true,
  }
);

module.exports = mongoose.model("Document", DocumentSchema);
