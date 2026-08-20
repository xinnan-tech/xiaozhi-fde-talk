export const baseUrlApi = (url: string) =>
  process.env.NODE_ENV === "development"
    ? `${url}`
    : `${import.meta.env.VITE_API_URL}${url}`;
