(function () {
  'use strict';

  const releaseApi = 'https://api.github.com/repos/ctsai0124/smart-document-organizer/releases/latest';
  const releasesPage = 'https://github.com/ctsai0124/smart-document-organizer/releases/latest';
  const status = document.getElementById('release-status');
  const releaseLinks = document.querySelectorAll('[data-release-link]');
  const releaseLabels = document.querySelectorAll('[data-release-label]');
  const releaseIcons = document.querySelectorAll('[data-release-icon]');
  const releaseDetailsLink = document.getElementById('release-details-link');
  const checksumLink = document.getElementById('checksum-link');

  function isAllowedGithubUrl(value) {
    try {
      const url = new URL(value);
      return url.protocol === 'https:' && (
        url.hostname === 'github.com' ||
        url.hostname === 'api.github.com'
      );
    } catch (error) {
      return false;
    }
  }

  function updateDownloadLinks(url, label, icon, openInNewTab) {
    releaseLinks.forEach((link) => {
      link.href = url;
      if (openInNewTab) {
        link.target = '_blank';
      } else {
        link.removeAttribute('target');
      }
    });
    releaseLabels.forEach((item) => { item.textContent = label; });
    releaseIcons.forEach((item) => { item.textContent = icon; });
  }

  function useFallback(message) {
    updateDownloadLinks(releasesPage, '查看 GitHub 最新版本', '↗', true);
    if (releaseDetailsLink) releaseDetailsLink.href = releasesPage;
    if (checksumLink) checksumLink.hidden = true;
    if (status) status.textContent = message;
  }

  fetch(releaseApi, { headers: { Accept: 'application/vnd.github+json' } })
    .then((response) => {
      if (!response.ok) throw new Error(`GitHub returned ${response.status}`);
      return response.json();
    })
    .then((release) => {
      if (!release || typeof release !== 'object') {
        throw new Error('GitHub returned an invalid release payload');
      }
      const installer = Array.isArray(release.assets)
        ? release.assets.find((asset) => (
          /SmartDocumentOrganizer.*Setup.*\.exe$/i.test(String(asset.name || '')) &&
          isAllowedGithubUrl(asset.browser_download_url)
        ))
        : null;
      const checksum = Array.isArray(release.assets)
        ? release.assets.find((asset) => (
          /SmartDocumentOrganizer.*Setup.*\.exe\.sha256$/i.test(String(asset.name || '')) &&
          isAllowedGithubUrl(asset.browser_download_url)
        ))
        : null;
      const version = String(release.tag_name || '').replace(/^v/i, '');
      if (!installer) {
        useFallback(version ? `最新版本 ${version}｜請到版本頁選擇安裝檔` : '請到版本頁選擇安裝檔');
        return;
      }
      updateDownloadLinks(installer.browser_download_url, `下載 Windows ${version || '最新版'}`, '↓', false);
      if (releaseDetailsLink && isAllowedGithubUrl(release.html_url)) {
        releaseDetailsLink.href = release.html_url;
      }
      if (checksumLink) {
        if (checksum) {
          checksumLink.href = checksum.browser_download_url;
          checksumLink.hidden = false;
        } else {
          checksumLink.hidden = true;
        }
      }
      const installerSize = Number(installer.size);
      const sizeLabel = Number.isFinite(installerSize)
        ? `${(installerSize / 1024 / 1024).toFixed(1)} MB`
        : '檔案大小請見 GitHub';
      if (status) status.textContent = `版本 ${version || '最新版'}｜Windows x64｜${sizeLabel}`;
    })
    .catch(() => useFallback('安裝檔資訊暫時無法讀取，可前往 GitHub 版本頁下載。'));
})();
