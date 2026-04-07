/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: false,
  },
  allowedDevOrigins: [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://172.30.192.1:3000",
    "http://192.168.10.8:3000"
  ]
};

export default nextConfig;
