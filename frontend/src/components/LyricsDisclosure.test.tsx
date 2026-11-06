import '@testing-library/jest-dom/vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { LyricsDisclosure } from './LyricsDisclosure';

describe('LyricsDisclosure', () => {
  it('starts collapsed, expands by keyboard, and focuses the lyrics', async () => {
    const user = userEvent.setup();
    render(<LyricsDisclosure><p>First lyric</p></LyricsDisclosure>);
    const toggle = screen.getByRole('button', { name: /lyrics/i });

    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('First lyric')).not.toBeInTheDocument();

    toggle.focus();
    await user.keyboard('{Enter}');

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('First lyric')).toBeVisible();
    expect(await screen.findByRole('heading', { name: 'Synced lyrics' })).toHaveFocus();
  });
});
