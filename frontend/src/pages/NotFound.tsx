import { Link } from 'react-router';
import { Page } from '../components/Layout';

export function NotFound() {
  return (
    <Page>
      <h1 className="font-headline text-3xl font-bold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block text-primary">
        Back to Discover
      </Link>
    </Page>
  );
}
