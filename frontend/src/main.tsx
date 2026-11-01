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
import './index.css';

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <Discover /> },
      { path: '/search', element: <Search /> },
      { path: '/songs/:songId', element: <SongPage /> },
      { path: '/upload', element: <Upload /> },
      { path: '/playlists', element: <Playlists /> },
      { path: '/playlists/:playlistId', element: <PlaylistDetail /> },
      { path: '/jam', element: <JamLobby /> },
      { path: '/jam/:jamId', element: <JamRoom /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PlayerProvider>
      <RouterProvider router={router} />
    </PlayerProvider>
  </StrictMode>,
);
