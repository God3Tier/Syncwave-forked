import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router';
import { Layout } from './components/Layout';
import { Discover } from './pages/Discover';
import { JamLobby } from './pages/JamLobby';
import { JamRoom } from './pages/JamRoom';
import { NotFound } from './pages/NotFound';
import { PlaylistDetail } from './pages/PlaylistDetail';
import { Playlists } from './pages/Playlists';
import { Search } from './pages/Search';
import { SongPage } from './pages/Song';
import { Upload } from './pages/Upload';
import { PlayerProvider } from './player/PlayerProvider';
import { AuthProvider } from './auth/AuthProvider';
import { AccountPage } from './pages/Account';
import { RequireAccount } from './auth/RequireAccount';
import './index.css';

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <Discover /> },
      { path: '/search', element: <Search /> },
      { path: '/songs/:songId', element: <SongPage /> },
      { path: '/playlists', element: <Playlists /> },
      { path: '/playlists/:playlistId', element: <PlaylistDetail /> },
      { path: '/jam', element: <JamLobby /> },
      { path: '/jam/:jamId', element: <JamRoom /> },
      {
        element: <RequireAccount />,
        children: [
          { path: '/upload', element: <Upload /> },
        ],
      },
      { path: '/login', element: <AccountPage mode="login" /> },
      { path: '/signup', element: <AccountPage mode="signup" /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PlayerProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </PlayerProvider>
  </StrictMode>,
);
