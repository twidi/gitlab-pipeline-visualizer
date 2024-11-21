chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    switch (message.type) {
        case 'getQuery':
            fetch(`${message.gitlabVizHost}/get_query?project_path=${message.projectPath}&pipeline_id=${message.pipelineId}&next_page_cursor=${message.nextPageCursor || ''}`)
                .then(response => response.json())
                .then(data => sendResponse(data))
                .catch(error => sendResponse({ error: error.message }));
            return true;

        case 'getVizData':
            const formData = new FormData();
            formData.append("pipeline_data", JSON.stringify(message.graphQLData));
            formData.append("mode", message.mode);

            fetch(`${message.gitlabVizHost}/visualize`, {
                method: "POST",
                body: formData
            }).then(response => response.json())
              .then(data => sendResponse(data))
              .catch(error => sendResponse({ error: error.message }));
            return true;
    }
});
