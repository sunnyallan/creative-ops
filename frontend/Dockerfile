FROM node:20-alpine

WORKDIR /app

# Copy manifest first for layer caching
COPY package.json ./

# Install with legacy peer deps so future minor version drift doesn't break the build
RUN npm install --legacy-peer-deps --no-audit --no-fund

COPY . .

EXPOSE 3000
CMD ["npm", "run", "dev"]
