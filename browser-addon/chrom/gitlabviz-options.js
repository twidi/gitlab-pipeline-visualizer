function saveOptions(e) {
  if (e) { e.preventDefault(); }
  chrome.storage.sync.set({
    gitlabVizHost: document.getElementById("gitlabVizHost").value
  });
}

function updateUI(gitlabVizHost) {
    document.getElementById("gitlabVizHost").value = gitlabVizHost;
}

function restoreOptions() {
  chrome.storage.sync.get({
      gitlabVizHost: DEFAULT_CONFIG.gitlabVizHost
    },
    (result) => {
      document.getElementById("gitlabVizHostText").textContent = DEFAULT_CONFIG.gitlabVizHost;
      updateUI(result.gitlabVizHost);
    }
  )
}

function resetOptions(e) {
  if (e) { e.preventDefault(); }
  updateUI(DEFAULT_CONFIG.gitlabVizHost);
  saveOptions()
}

document.addEventListener('DOMContentLoaded', restoreOptions);
document.querySelector("form").addEventListener("submit", saveOptions);
document.querySelector("form button[type='reset']").addEventListener("click", resetOptions);
