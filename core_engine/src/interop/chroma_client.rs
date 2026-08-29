use reqwest::{Client, Error};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// Define the payload structure for querying ChromaDB
#[derive(Serialize)]
struct ChromaQuery {
    query_texts: Vec<String>,
    n_results: u32,
}

// Define the structure for receiving ChromaDB results
#[derive(Deserialize, Debug)]
pub struct ChromaResult {
    pub ids: Vec<Vec<String>>,
    pub documents: Vec<Vec<String>>,
    pub metadatas: Vec<Vec<HashMap<String, String>>>,
    pub distances: Vec<Vec<f32>>,
}

pub struct SkillVectorClient {
    http_client: Client,
    base_url: String,
    collection_name: String,
}

impl SkillVectorClient {
    /// Initializes the connection to the local ChromaDB instance
    pub fn new(collection_name: &str) -> Self {
        Self {
            http_client: Client::new(),
            base_url: "http://localhost:8000/api/v1".to_string(), // Default local ChromaDB port
            collection_name: collection_name.to_string(),
        }
    }

    /// Queries the vector database for the closest semantic automation scripts
    pub async fn retrieve_skill(&self, user_prompt: &str, top_k: u32) -> Result<ChromaResult, Error> {
        let endpoint = format!(
            "{}/collections/{}/query",
            self.base_url, self.collection_name
        );

        let payload = ChromaQuery {
            query_texts: vec![user_prompt.to_string()],
            n_results: top_k,
        };

        let response = self.http_client
            .post(&endpoint)
            .json(&payload)
            .send()
            .await?;

        let search_results = response.json::<ChromaResult>().await?;
        Ok(search_results)
    }
}