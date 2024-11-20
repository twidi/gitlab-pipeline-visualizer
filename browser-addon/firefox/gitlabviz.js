function validatePipelineUrl(url) {
    try {
        // Parse URL
        const parsedUrl = new URL(url);

        // Split path and remove empty parts
        const pathParts = parsedUrl.pathname.split('/').filter(p => p);

        // Check format
        const pipelineIndex = pathParts.indexOf('pipelines');
        if (pipelineIndex < 2 || pathParts[pipelineIndex - 1] !== '-') {
            throw new Error();
        }

        // Get pipeline ID and verify it's a number
        const pipelineId = pathParts[pipelineIndex + 1];
        if (!/^\d+$/.test(pipelineId)) {
            throw new Error();
        }

        // Get project path
        const projectPath = pathParts.slice(0, pipelineIndex - 1).join('/');

        return {
            gitlabUrl: `${parsedUrl.protocol}//${parsedUrl.host}`,
            projectPath,
            pipelineId
        };
    } catch (e) {
        return null;
    }
}

async function getgraphQLData(gitlabHost, query, variables) {
	const queryParam = encodeURIComponent(query);
	const variablesParam = encodeURIComponent(JSON.stringify(variables));
	response = await fetch(`${gitlabHost}/api/graphql?query=${queryParam}&variables=${variablesParam}`);
	return await response.json();
}

async function handleMode(container, mode, gitlabVizHost, graphQLData) {
    let link = container.querySelector(`a.gitlabviz-link-${mode}`);
    if (!link) {
        link = document.createElement('a');
        link.target = "_blank";
        container.appendChild(link);
    }
    let img = container.querySelector(`img.gitlabviz-img-${mode}`);
    if (!img) {
        img = document.createElement("img");
        img.setAttribute("style", "max-width: 100%");
        link.appendChild(img);
    }

    const data = await sendMessage({
        type: 'getVizData',
        gitlabVizHost: gitlabVizHost,
        graphQLData: graphQLData,
        mode: mode
    });
    if (!reponse || response?.error) {
        link.style.display = "none";
    } else {
        img.src = data.pngUrl;
        link.href = data.viewUrl;
        link.style.display = "unset";
    }
}

function getStorageData() {
    return new Promise((resolve) => {
        chrome.storage.sync.get('gitlabVizHost', (items) => {
            resolve({
                gitlabVizHost: items.gitlabVizHost || DEFAULT_CONFIG.gitlabvizHost
            });
        });
    });
};

function sendMessage(message) {
    return new Promise((resolve) => {
        chrome.runtime.sendMessage(message, (response) => {
            resolve(response);
        });
    });
};

async function runForUrl(parsedUrl) {

    const { gitlabVizHost } = await getStorageData();

    try {
        const response = await sendMessage({
            type: 'fetchConfig',
            gitlabVizHost: gitlabVizHost,
            projectPath: parsedUrl.projectPath,
            pipelineId: parsedUrl.pipelineId
        });
        if (!reponse || response?.error) { throw new Error(response.error); }
    	const graphQLData = await getgraphQLData(parsedUrl.gitlabUrl, response.graphql_query, response.graphql_variables);

        let container = document.getElementById("gitlabviz-container");
        if (!container) {
            container = document.createElement('div');
            container.id = "gitlabviz-container";
            container.setAttribute("style", "width: 100%");
            document.querySelector(".js-pipeline-container").insertAdjacentElement("afterend", container);
        }

        await handleMode(container, "timeline", gitlabVizHost, graphQLData);
        await handleMode(container, "deps", gitlabVizHost, graphQLData);

    } catch(e) {
        console.log(e);
    }
}

const parsedUrl = validatePipelineUrl(window.location.href);
if (parsedUrl) { runForUrl(parsedUrl); }
