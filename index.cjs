'use strict';

const fs = require('fs');
const path = require('path');

const TB = path.join(__dirname, 'skills/time-sense/scripts/tb.py');
const ENTRY = fs
  .readFileSync(path.join(__dirname, 'rules/time-sense.md'), 'utf8')
  .split('{{TB}}')
  .join(TB)
  .trim();

module.exports = function timeSensePlugin(pi) {
  if (!pi || typeof pi.on !== 'function') return;
  pi.on('before_agent_start', async (event) => {
    const base = Array.isArray(event?.systemPrompt) ? event.systemPrompt : [];
    if (base.indexOf(ENTRY) !== -1) return undefined;
    return { systemPrompt: base.concat([ENTRY]) };
  });
};
