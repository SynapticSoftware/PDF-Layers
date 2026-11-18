import { cpSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const pdfAssets = ['cmaps', 'iccs', 'standard_fonts', 'wasm'];
const pdfRoot = resolve('node_modules/pdfjs-dist');

export default defineConfig({
  base: './',
  plugins: [
    react(),
    {
      name: 'local-pdf-rendering-assets',
      configureServer(server) {
        server.middlewares.use('/pdf-assets', (request, response, next) => {
          const path = request.url?.split('?')[0] ?? '';
          if (!pdfAssets.some((directory) => path.startsWith('/' + directory + '/')) ||
              path.includes('..') || path.includes('%')) {
            return next();
          }
          response.writeHead(302, { Location: '/node_modules/pdfjs-dist' + path });
          response.end();
        });
      },
      writeBundle({ dir }) {
        for (const directory of pdfAssets) {
          const source = resolve(pdfRoot, directory);
          if (existsSync(source)) {
            cpSync(source, resolve(dir, 'pdf-assets', directory), { recursive: true });
          }
        }
      },
    },
  ],
});
