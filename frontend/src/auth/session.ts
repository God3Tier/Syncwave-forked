import type { Account } from '../api/auth';

let signedInAccount: Account | null = null;

export function setSignedInAccount(account: Account | null): void {
  signedInAccount = account;
}

export function getSignedInAccount(): Account | null {
  return signedInAccount;
}
