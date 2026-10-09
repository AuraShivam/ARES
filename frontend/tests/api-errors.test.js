import test from 'node:test'
import assert from 'node:assert/strict'

import { describeApiError } from '../src/lib/errors.js'

test('formats nested DRF field errors without losing child details', () => {
  assert.equal(
    describeApiError({ title: ['This field is required.'], actions: [{ owner: ['This field is required.'] }] }),
    'Title: This field is required. · Actions: Owner: This field is required.',
  )
})

test('keeps API detail messages readable', () => {
  assert.equal(describeApiError({ detail: 'Your ARES session expired. Sign in again.' }), 'Your ARES session expired. Sign in again.')
})

test('handles missing and array error payloads', () => {
  assert.equal(describeApiError(null), '')
  assert.equal(describeApiError(['First issue.', 'Second issue.']), 'First issue. · Second issue.')
})
