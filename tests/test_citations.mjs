import assert from 'node:assert/strict';
import {citationGroups} from '../web/markdown.js';
const groups=citationGroups('One [28:353], grouped [28:765, 28:989; 28:287], and [ 381:13 ].');
assert.deepEqual(groups.map(g=>g.ids),[['28:353'],['28:765','28:989','28:287'],['381:13']]);
assert.equal(citationGroups('[28:353, prose] [1] [https://example.com]').length,0);
assert.equal(groups[1].text,'[28:765, 28:989; 28:287]');
console.log('Single and grouped citation parsing checks passed.');
