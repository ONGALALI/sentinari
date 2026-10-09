Write a Comprehensive Model Card
A well-crafted model card (the README.md in your repository) is essential for discoverability, reproducibility, and effective sharing. Make sure to cover:

Metadata Configuration: The metadata section (YAML) at the top of your model card is key for search and categorization. Include:

Copied

pipeline_tag: text-generation    # Specify the task
library_name: transformers       # Specify the library
language:
  - en                           # List languages your model supports
license: apache-2.0              # Specify a license
datasets:
  - username/dataset             # List datasets used for training
base_model: username/base-model  # If applicable (your model is a fine-tune, quantized, merged version of another model)
tags:                            # Add extra tags which would make the repo searchable using the tag
  - tag1 
  - tag2
If you create the README.md in the Web UI, you’ll see a form with the most important metadata fields we recommend 🤗.

metadata template on the hub ui
Metadata Form on the Hub UI
Detailed Model Description: Provide a clear explanation of what your model does, its architecture, and its intended use cases. Help users quickly decide if it fits their needs.

Usage Examples: Provide clear, copy-and-run code snippets for inference, fine-tuning, or other common tasks. Keep edits needed by users to a minimum.

Bonus: Add a well-structured notebook.ipynb in the repo showing inference or fine-tuning, so users can open it in Google Colab and Kaggle Notebooks directly.

colab and kaggle button
Google and Kaggle Usage Buttons
Technical Specifications: Include training parameters, hardware needs, and other details that help users run the model effectively.

Performance Metrics: Share benchmarks and evaluation results. Include quantitative metrics and qualitative examples to show strengths and limitations.

Limitations and Biases: Document known limitations, biases, and ethical considerations so users can make informed choices.

To make the process more seamless, click Import model card template to pre-fill the README.mds with placeholders.

model card template button on the hub ui	model card template on the hub
The button to import the model card template	A section of the imported template
Enhance Model Discoverability and Usability
To maximize reach and usability:

Library Integration: Add support for one of the many libraries integrated with the Hugging Face Hub (such as transformers, diffusers, sentence-transformers, timm). This integration significantly increases your model’s accessibility and provides users with code snippets for working with your model.

For example, to specify that your model works with the transformers library:

Copied

library_name: transformers
code snippet tab
Code snippet tab
You can also register your own model library or add Hub support to your library and codebase, so the users know how to download model weights from the Hub.

We wrote an extensive guide on uploading best practices here.

Using a registered library also allows you to track downloads of your model over time.

Correct Metadata:

Pipeline Tag: Choose the correct pipeline tag so your model shows up in the right searches and widgets.
Examples of common pipeline tags:

text-generation - For language models that generate text

text-to-image - For text-to-image generation models

image-text-to-text - For vision-language models (VLMs) that generate text

text-to-speech - For models that generate audio from text

License: License information is crucial for users to understand how they can use the model.

Research Papers: If your model has associated papers, cite them in the model card. They will be cross-linked automatically.

Copied
## References

* [Model Paper](https://arxiv.org/abs/xxxx.xxxxx)
Collections: If you’re releasing multiple related models or variants, organize them into a collection. Collections help users discover related models and understand relationships across versions.

Demos: Create a Hugging Face Space with an interactive demo. This lets users try your model without writing code. You can also link the model from the Space to make it appear on the model page UI.

Copied
## Demo

Try this model directly in your browser: [Space Demo](https://huggingface.co/spaces/username/model-demo)
When you create a demo, download the model from its Hub repository (not external sources like Google Drive). This cross-links artifacts and improves visibility

Quantized Versions: Consider uploading quantized versions (for example, GGUF) on a separate repository to improve accessibility for users with limited compute. Link these versions using the base_model metadata field on the quantized model cards, and document performance differences.

Copied

base_model: username/original-model
base_model_relation: quantized
model tree showcasing relations
Model tree showing quantized versions
Linking Datasets on the Model Page: Link datasets in your metadata so they appear directly on your model page.

Copied

datasets:
- username/dataset
- username/dataset-2
New Model Version: If your model is an update of an existing one, specify it on the older model’s card. This will display a banner on the older page linking to the update.

Copied

new_version: username/updated-model
Visual Examples: For image or video generation models, include examples directly on your model page using the <Gallery> card component.

Copied
<Gallery>
![Example 1](./images/example1.png)
![Example 2](./images/example2.png)
</Gallery>
Carbon Emissions: If possible, specify the carbon emissions from training.

Copied

co2_eq_emissions:
  emissions: 123.45
  source: "CodeCarbon"
  training_type: "pre-training"
  geographical_location: "US-East"
  hardware_used: "8xA100 GPUs"
Access Control and Visibility
Visibility Settings: When ready to share your model, switch it to public in your model settings. Before doing so, double-check that all documentation and code examples to ensure they’re accurate and complete.

Gated Access: If your model needs controlled access, use the gated access feature and clearly state the conditions users must meet. This is important for models with dual-use concerns or commercial restrictions.

🏁 After Releasing Your Model
A successful model release extends beyond the initial publication. To maintain quality and maximize impact:

Maintenance and Community Engagement
Verify Functionality: After release, test all code snippets in a clean environment to confirm they work as expected. This ensures users can run your model without errors or confusion.

For example, if your model is a transformers compatible LLM:

Copied
from transformers import pipeline

# This should run without errors
pipe = pipeline("text-generation", model="your-username/your-model")
result = pipe("Your test prompt")
print(result)
Share Share Share: Most users discover models through social media, chat channels (like Slack or Discord), or newsletters. Share your model links in these spaces, and also add them to your website or GitHub repositories.

The more visits and likes your model receives, the higher it appears on the Hugging Face Trending section, bringing even more visibility

Community Interaction: Use the Community tab to answer questions, address feedback, and resolve issues promptly. Clarify confusion, accept helpful suggestions, and close off-topic threads to keep discussions focused.

Add Evaluation Results
If you evaluate on any of the supported benchmark datasets on the Hub, you can add evaluation results to your model repository. This will make benchmark scores visible directly on the model page and benchmark leaderboard in the dataset repository. See the Evaluation Results documentation for the full specification.

To add evaluation results, create YAML files in the .eval_results/ folder of your model repository. Each file references a Hub Benchmark dataset:

Copied
# .eval_results/gpqa.yaml
- dataset:
    id: Idavidrein/gpqa
    task_id: diamond
  value: 76.1
  date: "2026-03-19"
  source:
    url: https://huggingface.co/your-org/your-model
    name: Model Card
    user: your-username
The task_id must match a task defined in the benchmark dataset’s eval.yaml. You can find available benchmarks and their task IDs by checking the eval.yaml file in benchmark dataset repos like HLE.

Anyone in the community can also submit evaluation results to any model by opening a Pull Request. Community-submitted scores display a “community” badge on the model page. To streamline this process, you can use the community-evals repository, which provides scripts and an agent skill for extracting scores from model cards and creating PRs automatically.

Tracking Usage and Impact
Usage Metrics: Track downloads and likes to understand your model’s reach and adoption. You can view total download metrics in your model’s settings.

Review Community Contributions: Regularly check your model’s repository for contributions from other users. Community pull requests and discussions can provide useful feedback, ideas, and opportunities for collaboration.

🏢 Enterprise Features
Hugging Face Team & Enterprise subscription offers additional capabilities for teams and organizations:

Access Control: Set resource groups to manage access for specific teams or users. This ensures the right permissions and secure collaboration across your organization.

Storage Region: Choose the data storage region (US or EU) for your model files to meet regional data regulations and compliance requirements.

Advanced Analytics: Use Publisher Analytics to gain deeper insights into model usage patterns, downloads, and adoption trends across your organization.

Extended Storage: Access additional private storage capacity to host more models and larger artifacts as your model portfolio expands.

Organization Blog Posts: Enterprise organizations can now publish blog articles directly on Hugging Face. This lets you share model releases, research updates, and announcements with the broader community, all from your organization’s profile.

By following these guidelines and examples, you’ll make your model release on Hugging Face clear, useful, and impactful. This helps your work reach more people, strengthens the AI community, and increases your model’s visibility.

We can’t wait to see what you share next! 