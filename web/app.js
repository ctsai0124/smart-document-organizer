(function () {
  'use strict';

  const releaseApi = 'https://api.github.com/repos/ctsai0124/smart-document-organizer/releases/latest';
  const releasesPage = 'https://github.com/ctsai0124/smart-document-organizer/releases/latest';
  const downloadButton = document.getElementById('download-button');
  const status = document.getElementById('release-status');
  const releaseLinks = document.querySelectorAll('[data-release-link]');

  function useFallback(message) {
    if (downloadButton) downloadButton.href = releasesPage;
    releaseLinks.forEach((link) => { link.href = releasesPage; });
    if (status) status.textContent = message;
  }

  fetch(releaseApi, { headers: { Accept: 'application/vnd.github+json' } })
    .then((response) => {
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
      return response.json();
    })
    .then((release) => {
      const installer = Array.isArray(release.assets)
        ? release.assets.find((asset) => /SmartDocumentOrganizer.*Setup.*\.exe$/i.test(asset.name))
        : null;
      const version = String(release.tag_name || '').replace(/^v/i, '');
      if (!installer) {
        useFallback(version ? `最新版本 ${version}｜請到版本頁選擇安裝檔` : '請到版本頁選擇安裝檔');
        return;
      }
      if (downloadButton) {
        downloadButton.href = installer.browser_download_url;
        downloadButton.querySelector('span').textContent = `下載 Windows ${version || '最新版'}`;
      }
      releaseLinks.forEach((link) => { link.href = installer.browser_download_url; });
      if (status) status.textContent = `版本 ${version || '最新版'}｜Windows x64｜${(installer.size / 1024 / 1024).toFixed(1)} MB`;
    })
    .catch(() => useFallback('安裝檔資訊暫時無法讀取，可前往 GitHub 版本頁下載。'));
})();
