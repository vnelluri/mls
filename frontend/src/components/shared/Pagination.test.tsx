import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { Pagination } from './Pagination';

describe('Pagination', () => {
  it('renders nothing when there are no results', () => {
    const { container } = render(
      <Pagination data={{ total: 0, page: 1, pageSize: 20 }} onPageChange={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the visible range and disables Previous on the first page', () => {
    render(<Pagination data={{ total: 45, page: 1, pageSize: 20 }} onPageChange={() => {}} />);
    expect(screen.getByText('Showing 1-20 of 45')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled();
  });

  it('clamps the last page range and disables Next', () => {
    render(<Pagination data={{ total: 45, page: 3, pageSize: 20 }} onPageChange={() => {}} />);
    expect(screen.getByText('Showing 41-45 of 45')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Previous' })).toBeEnabled();
  });

  it('emits the adjacent page numbers', () => {
    const onPageChange = vi.fn();
    render(<Pagination data={{ total: 45, page: 2, pageSize: 20 }} onPageChange={onPageChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    expect(onPageChange).toHaveBeenNthCalledWith(1, 1);
    expect(onPageChange).toHaveBeenNthCalledWith(2, 3);
  });

  it('treats a single short page as one page', () => {
    render(<Pagination data={{ total: 5, page: 1, pageSize: 20 }} onPageChange={() => {}} />);
    expect(screen.getByText('Showing 1-5 of 5')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled();
  });
});
