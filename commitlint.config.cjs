// Conventional Commits enforcement. See .github/SCOPES.md for the scope catalog.
module.exports = {
  extends: ['@commitlint/config-conventional'],
  rules: {
    'type-enum': [
      2,
      'always',
      ['feat', 'fix', 'perf', 'refactor', 'docs', 'test', 'build', 'ci', 'chore', 'style', 'revert'],
    ],
    'scope-empty': [2, 'never'],
    'scope-enum': [
      2,
      'always',
      [
        'mqtt', 'spoolman', 'spoolmandb', 'db', 'consumption', 'jobs', 'tags',
        'kcatalog', 'cloud', 'presets', 'labels', 'ams', 'esp32', 'api', 'ui',
        'config', 'scripts', 'docker', 'ci', 'docs', 'deps', 'release',
        'auth', 'settings', 'providers', 'events', 'pwa', 'brand', 'repo', 'security',
      ],
    ],
    'subject-case': [2, 'never', ['sentence-case', 'start-case', 'pascal-case', 'upper-case']],
    // Raised from 100 to accommodate Dependabot-style headers.
    'header-max-length': [2, 'always', 120],
  },
};
