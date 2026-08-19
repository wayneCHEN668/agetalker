/**
 * 后端服务地址，唯一来源。
 *
 * 之前 6 个文件里各写死一份 'http://localhost:8050'，改服务器地址得挨个改、
 * 极易漏改。现在只改这一处。
 */

export const API_HOST = '47.253.82.38';
export const API_PORT = 8050;

export const API_BASE_URL = `http://${API_HOST}:${API_PORT}`;
export const WS_BASE_URL = `ws://${API_HOST}:${API_PORT}`;
