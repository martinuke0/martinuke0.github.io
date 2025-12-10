---
title: "A Detailed Guide to Using the n8n API with Python"
date: "2025-12-10T22:41:34.458"
draft: false
tags: ["n8n", "API", "Python", "Workflow Automation", "Integration"]
---

n8n is a powerful open-source workflow automation tool that combines the ease of visual programming with the flexibility of code. For Python developers looking to programmatically interact with n8n or extend its capabilities, understanding the n8n API and how to use it with Python is essential. This article provides a detailed overview of the n8n API and how to leverage it effectively using Python, including native Python scripting within n8n workflows and external API integrations.

## Table of Contents
- [Introduction to n8n and Its API](#introduction-to-n8n-and-its-api)
- [Authentication and API Basics](#authentication-and-api-basics)
- [Using Python Within n8n Workflows](#using-python-within-n8n-workflows)
- [Interacting with the n8n REST API Using Python](#interacting-with-the-n8n-rest-api-using-python)
- [Python SDKs and Tools for n8n](#python-sdks-and-tools-for-n8n)
- [Example: Importing Workflows via Python](#example-importing-workflows-via-python)
- [Best Practices and Tips](#best-practices-and-tips)
- [Conclusion](#conclusion)

---

## Introduction to n8n and Its API

n8n is a low-code/no-code workflow automation platform that allows users to connect APIs, automate repetitive tasks, and build integrations visually. Its strength lies in combining drag-and-drop workflow design with the ability to embed custom code, such as JavaScript or Python, for advanced logic.

n8n exposes a **public REST API** that lets you programmatically manage workflows, executions, credentials, and more — essentially enabling you to do everything you can in the UI through code. This API is especially useful for integrating n8n into existing Python applications, automating deployment or management tasks, or building custom interfaces[3][5].

---

## Authentication and API Basics

- **Authentication**: The n8n API uses **API key authentication**. You generate an API key in your n8n instance and include it in your HTTP request headers to authenticate[6].

- **API Endpoints**: The core API supports endpoints for:
  - Listing workflows
  - Fetching workflow details
  - Downloading workflow JSON files
  - Getting workflow execution stats, and more[1][3]

- **API Playground**: If you self-host n8n, it provides an API playground for testing API calls interactively, which is helpful for prototyping Python scripts that call the API[3].

---

## Using Python Within n8n Workflows

n8n supports running Python code inside workflows using a **Code node**. Two Python modes have existed:

- **Pyodide (Legacy)**: A WebAssembly-based Python environment with limited packages, now deprecated[2].
  
- **Native Python (Recommended)**: Introduced in n8n v1.111.0 and stable in n8n v2, this mode runs Python code natively on the host machine and supports broader Python packages. It requires syntax adjustments such as using bracket notation (`item["json"]["field"]`) instead of dot notation[2].

This embedded Python enables data transformations, calling external APIs, or running custom logic directly in the workflow without leaving n8n.

### Key Points About Python in n8n Code Nodes

- Only `_items` (all-items mode) and `_item` (per-item mode) are supported as input variables.
- You cannot use some n8n-specific variables available in JavaScript nodes.
- Use bracket notation for JSON access.
- You can import additional packages if n8n is self-hosted and configured accordingly[2][4].

---

## Interacting with the n8n REST API Using Python

To control or automate n8n from an external Python application (like a Flask app), you can use Python's HTTP libraries (e.g., `requests`) to interact with the n8n REST API.

### Basic Workflow with Python `requests`

1. **Set API Key Header**

```python
headers = {
    "Authorization": "Bearer YOUR_N8N_API_KEY"
}
```

2. **List Workflows**

```python
import requests

url = "http://your-n8n-instance/api/workflows"
response = requests.get(url, headers=headers)

workflows = response.json()
print(workflows)
```

3. **Trigger Workflow Executions or Manage Workflows**

You can POST to execution endpoints or PUT to update workflows similarly.

This programmatic access enables you to embed n8n automation into your Python apps, perform bulk workflow management, or integrate with CI/CD pipelines[3][6].

---

## Python SDKs and Tools for n8n

While n8n does not officially provide a Python SDK, there are **unofficial Python SDKs** such as `n8n-sdk-python` available on PyPI, which wrap common API interactions for convenience[8]. These SDKs can simplify authentication, workflow retrieval, and execution management in Python projects.

Additionally, repositories such as [Zie619/n8n-workflows](https://github.com/Zie619/n8n-workflows) offer Python scripts to import/export workflows and interact with n8n locally via API[1]. These can be great starting points for building customized Python tooling around n8n.

---

## Example: Importing Workflows via Python

A common use case is automating workflow imports during deployment. Using a Python script, you can upload JSON workflow files to n8n:

```python
import requests

api_url = "http://localhost:5678/api/workflows"
api_key = "YOUR_API_KEY"
headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

with open("workflow.json", "r") as f:
    workflow_json = f.read()

response = requests.post(api_url, headers=headers, data=workflow_json)
if response.ok:
    print("Workflow imported successfully.")
else:
    print("Failed to import workflow:", response.text)
```

This mirrors functionality provided by the `import_workflows.py` script found in community repositories[1].

---

## Best Practices and Tips

- **Use Native Python in n8n for complex data tasks**: Native Python support is more robust than legacy Pyodide and integrates well with self-hosted Python environments[2].

- **Secure your API key**: Always keep your API key confidential and use secure HTTPS endpoints.

- **Test API calls with the n8n API playground**: This helps to understand endpoint behavior before coding in Python[3].

- **Consider unofficial SDKs but review code**: Since official SDKs are not available, vet community SDKs for compatibility and security[8].

- **Use environment variables** for API keys and endpoints in your Python scripts to keep code clean and secure.

---

## Conclusion

The n8n API combined with Python offers a powerful way to extend and automate your workflow automation infrastructure. Whether embedding Python code directly inside n8n workflows using the native Python Code node or controlling n8n externally via its REST API, Python developers have versatile options to integrate, customize, and scale their automations.

By mastering these methods, you can build sophisticated automation pipelines, integrate n8n into existing Python applications, and improve operational efficiencies with code and workflows working seamlessly together.

---

If you want to explore further, consider visiting the official n8n documentation on the REST API and the Code node, and check out community projects on GitHub that provide Python examples and tooling.