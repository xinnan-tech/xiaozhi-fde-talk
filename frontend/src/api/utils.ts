export const baseUrlApi = (url: string) =>
  process.env.NODE_ENV === "development"
    ? `${url}`
    : `http://192.168.4.119:8000${url}`;
