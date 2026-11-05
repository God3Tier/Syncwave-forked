import { Link } from 'react-router';
import { Page } from '../components/Layout';

export function NotFound() {
  return (
    <Page>
      <div className="max-w-lg py-16">
        <p className="text-sm font-bold text-primary">404</p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-[-0.04em]">That track ends here.</h1>
        <p className="mt-3 leading-7 text-on-surface-variant">The page may have moved, or the link may be incomplete.</p>
      <Link to="/" className="mt-6 inline-flex min-h-10 items-center rounded-xl bg-on-surface px-4 text-sm font-bold text-background">
        Go home
      </Link>
      </div>
    </Page>
  );
}
