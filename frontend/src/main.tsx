import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { injectThemeVars } from './theme/injectThemeVars';
import './theme/theme.css';
import { App } from './App';

injectThemeVars();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
