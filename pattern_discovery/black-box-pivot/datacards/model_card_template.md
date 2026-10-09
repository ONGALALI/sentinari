Template
modelcard_template.md file

Directions
Fully filling out a model card requires input from a few different roles. (One person may have more than one role.) We’ll refer to these roles as the developer, who writes the code and runs training; the sociotechnic, who is skilled at analyzing the interaction of technology and society long-term (this includes lawyers, ethicists, sociologists, or rights advocates); and the project organizer, who understands the overall scope and reach of the model, can roughly fill out each part of the card, and who serves as a contact person for model card updates.

The developer is necessary for filling out Training Procedure and Technical Specifications. They are also particularly useful for the “Limitations” section of Bias, Risks, and Limitations. They are responsible for providing Results for the Evaluation, and ideally work with the other roles to define the rest of the Evaluation: Testing Data, Factors & Metrics.

The sociotechnic is necessary for filling out “Bias” and “Risks” within Bias, Risks, and Limitations, and particularly useful for “Out of Scope Use” within Uses.

The project organizer is necessary for filling out Model Details and Uses. They might also fill out Training Data. Project organizers could also be in charge of Citation, Glossary, Model Card Contact, Model Card Authors, and More Information.

Instructions are provided below, in italics.

Template variable names appear in monospace.

Model Name
Section Overview: Provide the model name and a 1-2 sentence summary of what the model is.

model_id

model_summary

Table of Contents
Section Overview: Provide this with links to each section, to enable people to easily jump around/use the file in other locations with the preserved TOC/print out the content/etc.

Model Details
Section Overview: This section provides basic information about what the model is, its current status, and where it came from. It should be useful for anyone who wants to reference the model.

Model Description
model_description

Provide basic details about the model. This includes the architecture, version, if it was introduced in a paper, if an original implementation is available, and the creators. Any copyright should be attributed here. General information about training procedures, parameters, and important disclaimers can also be mentioned in this section.

Developed by: developers
List (and ideally link to) the people who built the model.

Funded by: funded_by
List (and ideally link to) the funding sources that financially, computationally, or otherwise supported or enabled this model.

Shared by [optional]: shared_by
List (and ideally link to) the people/organization making the model available online.

Model type: model_type
You can name the “type” as:

1. Supervision/Learning Method

2. Machine Learning Type

3. Modality

Language(s) [NLP]: language
Use this field when the system uses or processes natural (human) language.

License: license
Name and link to the license being used.

Finetuned From Model [optional]: base_model
If this model has another model as its base, link to that model here.

Model Sources optional
Repository: repo
Paper [optional]: paper
Demo [optional]: demo
Provide sources for the user to directly see the model and its details. Additional kinds of resources – training logs, lessons learned, etc. – belong in the More Information section. If you include one thing for this section, link to the repository.

Uses
Section Overview: This section addresses questions around how the model is intended to be used in different applied contexts, discusses the foreseeable users of the model (including those affected by the model), and describes uses that are considered out of scope or misuse of the model. Note this section is not intended to include the license usage details. For that, link directly to the license.

Direct Use
direct_use

Explain how the model can be used without fine-tuning, post-processing, or plugging into a pipeline. An example code snippet is recommended.

Downstream Use optional
downstream_use

Explain how this model can be used when fine-tuned for a task or when plugged into a larger ecosystem or app. An example code snippet is recommended.

Out-of-Scope Use
out_of_scope_use

List how the model may foreseeably be misused (used in a way it will not work for) and address what users ought not do with the model.

Bias, Risks, and Limitations
Section Overview: This section identifies foreseeable harms, misunderstandings, and technical and sociotechnical limitations. It also provides information on warnings and potential mitigations. Bias, risks, and limitations can sometimes be inseparable/refer to the same issues. Generally, bias and risks are sociotechnical, while limitations are technical:

A bias is a stereotype or disproportionate performance (skew) for some subpopulations.
A risk is a socially-relevant issue that the model might cause.
A limitation is a likely failure mode that can be addressed following the listed Recommendations.
bias_risks_limitations

What are the known or foreseeable issues stemming from this model?

Recommendations
bias_recommendations

What are recommendations with respect to the foreseeable issues? This can include everything from “downsample your image” to filtering explicit content.

Training Details
Section Overview: This section provides information to describe and replicate training, including the training data, the speed and size of training elements, and the environmental impact of training. This relates heavily to the Technical Specifications as well, and content here should link to that section when it is relevant to the training procedure. It is useful for people who want to learn more about the model inputs and training footprint. It is relevant for anyone who wants to know the basics of what the model is learning.

Training Data
training_data

Write 1-2 sentences on what the training data is. Ideally this links to a Dataset Card for further information. Links to documentation related to data pre-processing or additional filtering may go here as well as in More Information.

Training Procedure optional
Preprocessing
preprocessing

Detail tokenization, resizing/rewriting (depending on the modality), etc.

Speeds, Sizes, Times
speeds_sizes_times

Detail throughput, start/end time, checkpoint sizes, etc.

Evaluation
Section Overview: This section describes the evaluation protocols, what is being measured in the evaluation, and provides the results. Evaluation ideally has at least two parts, with one part looking at quantitative measurement of general performance (Testing Data, Factors & Metrics), such as may be done with benchmarking; and another looking at performance with respect to specific social safety issues (Societal Impact Assessment), such as may be done with red-teaming. You can also specify your model’s evaluation results in a structured way in the model card metadata. Results are parsed by the Hub and displayed in a widget on the model page. See https://huggingface.co/docs/hub/model-cards#evaluation-results.

Testing Data, Factors & Metrics
Evaluation is ideally disaggregated with respect to different factors, such as task, domain and population subgroup; and calculated with metrics that are most meaningful for foreseeable contexts of use. Equal evaluation performance across different subgroups is said to be “fair” across those subgroups; target fairness metrics should be decided based on which errors are more likely to be problematic in light of the model use. However, this section is most commonly used to report aggregate evaluation performance on different task benchmarks.

Testing Data
testing_data

Describe testing data or link to its Dataset Card.

Factors
testing_factors

What are the foreseeable characteristics that will influence how the model behaves? Evaluation should ideally be disaggregated across these factors in order to uncover disparities in performance.

Metrics
testing_metrics

What metrics will be used for evaluation?

Results
results

Results should be based on the Factors and Metrics defined above.

Summary
results_summary

What do the results say? This can function as a kind of tl;dr for general audiences.

Societal Impact Assessment optional
Use this free text section to explain how this model has been evaluated for risk of societal harm, such as for child safety, NCII, privacy, and violence. This might take the form of answers to the following questions:

Is this model safe for kids to use? Why or why not?
Has this model been tested to evaluate risks pertaining to non-consensual intimate imagery (including CSEM)?
Has this model been tested to evaluate risks pertaining to violent activities, or depictions of violence? What were the results?
Quantitative numbers on each issue may also be provided.

Model Examination optional
Section Overview: This is an experimental section some developers are beginning to add, where work on explainability/interpretability may go.

model_examination

Environmental Impact
Section Overview: Summarizes the information necessary to calculate environmental impacts such as electricity usage and carbon emissions.

Hardware Type: hardware_type
Hours used: hours_used
Cloud Provider: cloud_provider
Compute Region: cloud_region
Carbon Emitted: co2_emitted
Carbon emissions can be estimated using the Machine Learning Impact calculator presented in Lacoste et al. (2019).

Technical Specifications optional
Section Overview: This section includes details about the model objective and architecture, and the compute infrastructure. It is useful for people interested in model development. Writing this section usually requires the model developer to be directly involved.

Model Architecture and Objective
model_specs

Compute Infrastructure
compute_infrastructure

Hardware
hardware_requirements

What are the minimum hardware requirements, e.g. processing, storage, and memory requirements?

Software
software

Citation optional
Section Overview: The developers’ preferred citation for this model. This is often a paper.

BibTeX
citation_bibtex

APA
citation_apa

Glossary optional
Section Overview: This section defines common terms and how metrics are calculated.

glossary

Clearly define terms in order to be accessible across audiences.

More Information optional
Section Overview: This section provides links to writing on dataset creation, technical specifications, lessons learned, and initial results.

more_information

Model Card Authors optional
Section Overview: This section lists the people who create the model card, providing recognition and accountability for the detailed work that goes into its construction.

model_card_authors

Model Card Contact
Section Overview: Provides a way for people who have updates to the Model Card, suggestions, or questions, to contact the Model Card authors

model_card_contact

How to Get Started with the Model
Section Overview: Provides a code snippet to show how to use the model.

get_started_code

Please cite as: Ozoani, Ezi and Gerchick, Marissa and Mitchell, Margaret. Model Card Guidebook. Hugging Face, 2022. https://huggingface.co/docs/hub/en/model-card-guidebook