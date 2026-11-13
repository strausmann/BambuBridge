import { defineConfig } from "@vite-pwa/assets-generator/config";

// Icons are generated from the brand mark at build time (docs/brand/README.md), never kept by hand.
// The mark already is a rounded square with its own ground, so no padding and no extra background.
const plain = { padding: 0, resizeOptions: { background: "transparent" } } as const;

export default defineConfig({
  images: ["public/favicon.svg"],
  preset: {
    transparent: { sizes: [192, 512], favicons: [[48, "favicon.ico"]], ...plain },
    maskable: { sizes: [512], padding: 0.18, resizeOptions: { background: "#F3F7FB" } },
    apple: { sizes: [180], padding: 0.08, resizeOptions: { background: "#F3F7FB" } },
    assetName: (type, size) => {
      if (type === "maskable") return `icons/icon-maskable-${size.width}.png`;
      if (type === "apple") return `icons/apple-touch-icon-${size.width}.png`;
      return `icons/icon-${size.width}.png`;
    },
  },
});
