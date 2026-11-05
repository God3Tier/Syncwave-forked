import { request } from './http';

export interface Account {
  id: string;
  username: string;
}

export interface Credentials {
  username: string;
  password: string;
}

export const getAccount = () => request<Account>('/api/auth/me');
export const signUp = (credentials: Credentials) => request<Account>('/api/auth/signup', { method: 'POST', json: credentials });
export const logIn = (credentials: Credentials) => request<Account>('/api/auth/login', { method: 'POST', json: credentials });
export const logOut = () => request<void>('/api/auth/logout', { method: 'POST' });
