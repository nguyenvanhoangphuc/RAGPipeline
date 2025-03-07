from langchain_core.prompts import PromptTemplate
from langchain.schema.runnable import RunnableLambda
from my_utils import extract_json_from_string


class ModuleRAG: 
    def __init__(self, vllm_model):
        self.vllm_model = vllm_model
        self.runnable = RunnableLambda(extract_json_from_string)
        self.extract_reference_generator = self.create_extract_reference_generator()
        self.sematic_reference_generator = self.create_sematic_reference_generator()
        self.rewrite_clause_generator = self.create_rewrite_clause_generator()
        self.proposition_generator = self.create_proposition_generator()
        self.retrieval_grader = self.create_retrieval_grader()
        self.rag_chain_both = self.create_rag_chain_both()
        self.rag_chain_doc = self.create_rag_chain_doc()
        self.query_transformation_generator = self.create_query_transformation_generator()

    def create_extract_reference_generator(self):
        extract_reference_template="""<|im_start|>system
You will receive:
1. A passage from a contract that may include references to other sections, articles, clauses, or parts of the contract (e.g., “as specified in Section 2”, “according to the clause above”, “refer to Article 3 below”).
2. Metadata providing context for the current passage, including details such as the current Chapter, Article, and Clause.

### Task:
#### Step 1: Extract References
- Identify and extract all phrases in the contract text that refer to other sections, articles, or clauses.

#### Step 2: Resolve References
- Use the provided metadata to determine the specific Chapter, Article, or Clause that each reference points to.
- Examples:
- If the metadata indicates that the current passage is in Article 1:
    - "the above article" refers to Article 0 (or the last article of the previous section, if applicable).
    - "clause 3 below" refers to Clause 3 in the subsequent article or section.
- If a reference cannot be precisely resolved, set its "resolved" value to -1.
-"has_reference": "yes" if there is at least one reference, otherwise "no".
-"is_extractable": "yes" if the reference can be extracted and resolved, otherwise "no".
-"references": A list of extracted references, each containing:
-"text": The extracted reference phrase.
-"resolved": The resolved location, with -1 if it cannot be determined.

The response should be in following JSON format. The answer contain json only:
{{
"has_reference" : "yes" | "no",
"is_extractable" : "yes" | "no"
"references": [
    {{
    "text": str,
    "resolved": {{
        "Chapter": int| -1,
        "Article": int| -1,
        "clause": int| -1,
        "sub_clause": int|-1,
    }}
    }}
]
}}

<|im_end|>

<|im_start|>user
contract:{document}
metadata:{metadata}
<|im_end|>

<|im_start|>assistant
"""
        extract_reference_prompt = PromptTemplate.from_template(extract_reference_template)
        extract_reference_generator = extract_reference_prompt | self.vllm_model| self.runnable
        return extract_reference_generator

    def get_extract_reference_generator(self):
        return self.extract_reference_generator
    
    def create_sematic_reference_generator(self):
        sematic_reference_template = """<|im_start|>system
You are a language model specializing in analyzing relationships between texts. Your task is to determine whether a referenced text (Referenced Text) provides additional meaning that helps in understanding the main text (Main Text).

Task:
Check whether the referenced text provides necessary additional information to better understand the main text.

If the referenced text contains important supplementary information that clarifies, explains, or provides essential context for understanding the main text, respond with "yes".
If the referenced text does not add significant meaning or merely repeats existing information, respond with "no".

The response must be returned in following JSON format, return json only:
{{
"analysis": "A brief explanation of the relationship between the texts, must not include `"`.",
"provide_additional_meaning": "yes"|"no",

}}
<|im_end|>

<|im_start|>user
Main Text: {main_text}
Referenced Text: {referenced_text}
<|im_end|>

<|im_start|>assistant
"""
        sematic_reference_prompt = PromptTemplate.from_template(sematic_reference_template)
        sematic_reference_generator = sematic_reference_prompt | self.vllm_model| self.runnable
        return sematic_reference_generator

    def get_sematic_reference_generator(self):
        return self.sematic_reference_generator

    def create_rewrite_clause_generator(self):
        rewrite_clause_template = """<|im_start|>system
You are a legal text processing expert. Your task is to merge two contract sections into a single coherent text while ensuring clarity, accuracy, and legal consistency.

main_section: This is the primary contract section, which may reference specific clauses from another section.
refer_section: This section contains detailed information referenced in main_section.
Requirements:
1.If the main_section references a specific clause in the refer_section, replace the reference with the actual content from the refer_section.
2.Completely remove any reference phrases such as "as defined in clause X", "according to article Y", or any similar wording. The final text should only contain the actual content without referring back to any section or clause.
3.Preserve the original meaning of the contract without altering its legal intent.
4.Ensure the final merged text maintains a clear, structured, and legally sound format.
5.The final "generated_clause" must be self-contained and must not contain any reference phrases even if reference phrases are present in the refer_sections.
6.All newlines are represented using "\\n" instead of actual line breaks.
The response must be in following JSON format.:
{{
"analysis": "Logical reasoning behind how the generated clause was created, including how references were replaced.",
"generated_section": "The fully rewritten section with all references replaced by full content, properly formatted and structured, without any reference phrases.Ensure that in the JSON response"
}}
<|im_end|>

<|im_start|>user
main section:
{main_section}
refer sections:
{refer_sections}
<|im_end|>
<|im_start|>assistant
"""

        rewrite_clause_prompt = PromptTemplate.from_template(rewrite_clause_template)
        rewrite_clause_generator = rewrite_clause_prompt | self.vllm_model | self.runnable
        return rewrite_clause_generator

    def get_rewrite_clause_generator(self):
        return self.rewrite_clause_generator

    def create_proposition_generator(self): 
        proposition_template="""<|im_start|>system
The following input is a legal document or contract. Your task is to break down the document into simple, self-contained propositions that are easy to understand. Follow these steps:

1. Identify key sentences: 
Read the entire document and extract factual information, rules, or conditions. Ignore introductory or transitional phrases that do not contain substantial content.

2. Ensure completeness of definitions:  
- If a proposition defines a term (for example: "Xとは…"), ensure it contains a complete definition.  
- Do not generate incomplete propositions such as:  
    "A worker is defined as follows." → This does not provide a definition.  
    Instead, include the full definition within the same proposition:  
    "A worker is a person who joins the company according to the procedure set forth in Chapter 2 and meets the following criteria: [list of criteria]."  

3. Make each proposition self-contained:  
- Ensure the proposition is understandable without additional context.  
- Replace pronouns or vague references with explicit terms.  

4. Maintain accuracy and include all necessary details:  
- Retain legal references, dates, and conditions to avoid ambiguity.  
- If a rule contains multiple conditions, split them into separate propositions while preserving logical relationships.  

5. Avoid overlapping or redundant propositions:  
- Do not generate broad statements that are just incomplete versions of other propositions.  

6. Use appropriate legal or technical terms: Write all propositions in janpanese and use proper legal or technical terminology.
The response should be in Japanese and returned in following JSON format:
{{
"propositions": 
    [
    {{"proposition":"Generated proposition in japanese"}}
    ]
}}
<|im_end|>

<|im_start|>user
contract:{document}
<|im_end|>

<|im_start|>assistant
"""
        proposition_prompt = PromptTemplate.from_template(proposition_template)
        proposition_generator = proposition_prompt | self.vllm_model| self.runnable
        return proposition_generator

    def get_proposition_generator(self):
        return self.proposition_generator

    def create_retrieval_grader(self):
        retrieval_grader_template="""<|im_start|>system
You are an evaluator assessing the relevance of a retrieved law to a given contract segment.
Evaluation Criteria:
Answer "yes" only if the retrieved law can be used as direct evidence to determine whether the contract segment complies with the law or violates the law.
In all other cases, including where the law is not directly applicable or does not provide clear evidence of compliance or non-compliance, answer "no".
The law must have a direct and actionable link to the contract segment's compliance or violation of legal standards.

Your response should focus on whether the law can serve as direct evidence of the contract’s legal compliance or non-compliance.

Provide a binary score to indicate relevance:
"yes": The law provides direct evidence of the contract segment’s compliance or violation of the law.
"no": The law does not provide direct evidence regarding compliance or violation.

The response should be returned in following JSON format:
{{
"analysis": "your analysis steps, must not generate '"' in here",
"binary_score": "yes" |"no"
}}
<|im_end|>

<|im_start|>user
Law: [{context}].
Contract Segment: [{contract}]

<|im_end|>

<|im_start|>assistant
"""

        retrieval_grader_prompt = PromptTemplate.from_template(retrieval_grader_template)

        # Chain
        retrieval_grader = retrieval_grader_prompt | self.vllm_model | self.runnable
        return retrieval_grader

    def get_retrieval_grader(self):
        return self.retrieval_grader

    def create_rag_chain_both(self):
        template_both = """<|im_start|>system
You are a legal AI specializing in contract evaluation. Your task is to analyze a given contract clause and determine whether it *complies with, violates, or lacks sufficient information* to conclude compliance based on the provided legal provisions.

### *Inputs:*  
- *Laws:* Relevant legal provisions related to the contract.  
- *Contract Clause:* The specific contract segment to be evaluated.  
- *Rewritten Contract Clause:* An alternative, clearer version of the contract clause for better understanding.

### *Evaluation Criteria:*  
1. *Compliance:* The contract fully adheres to the relevant legal provisions.  
2. *Violation:* The contract contradicts or does not meet the legal requirements.  
3. *Insufficient Information:* The provided contract clause lacks enough details to determine compliance or violation.  

### *Response Format (in Japanese, JSON format):*  
json
{{
"evaluation": "compliance" | "violation" | "insufficient_information",
"explanation": "A concise explanation of why the contract complies, violates, or lacks sufficient information."
}}

<|im_end|>

<|im_start|>user
Laws: [{context}].  
Contract Clause: [{contract}].  
Rewritten Contract Clause: [{new_query}].  
<|im_end|>

<|im_start|>assistant
"""

        # Tạo PromptTemplate
        prompt_both = PromptTemplate.from_template(template_both)

        # Chuỗi chạy RAG
        rag_chain_both = prompt_both | self.vllm_model | self.runnable
        return rag_chain_both

    def get_rag_chain_both(self):
        return self.rag_chain_both

    def create_rag_chain_doc(self):
        template_doc = """<|im_start|>system
You are a legal AI specializing in contract evaluation. Your task is to analyze a given contract clause and determine whether it *complies with, violates, or lacks sufficient information* to conclude compliance based on the provided legal provisions.  

### *Inputs:*  
- *Laws:* Relevant legal provisions related to the contract.  
- *Contract Clause:* The specific contract segment to be evaluated.  

### *Evaluation Criteria:*  
1. *Compliance:* The contract fully adheres to the relevant legal provisions.  
2. *Violation:* The contract contradicts or does not meet the legal requirements.  
3. *Insufficient Information:* The provided contract clause lacks enough details to determine compliance or violation.  

### *Response Format (in Japanese, JSON format):*  
```json
{{
"evaluation": "compliance" | "violation" | "insufficient_information",
"explanation": "A concise explanation of why the contract complies, violates, or lacks sufficient information."
}}
<|im_end|>

<|im_start|>user
Laws: [{context}].
Contract Segment: [{contract}]

<|im_end|>

<|im_start|>assistant
"""

        # Create prompt
        prompt_doc = PromptTemplate.from_template(template_doc)

        rag_chain_doc = prompt_doc | self.vllm_model | self.runnable
        return rag_chain_doc

    def get_rag_chain_doc(self):
        return self.rag_chain_doc

    def create_query_transformation_generator(self):
        query_transformation_template="""<|im_start|>system
You are a natural language processing expert. Your task is to transform the input query into different variations based on the following criteria:  
### Instructions:  
1. **Paraphrasing (1 variations):** Rewrite the query in a different way while keeping the meaning unchanged.  
2. **Granularity Adjustment - More Detailed (1 variations):** Rewrite the query with a higher level of detail by adding specific elements without changing its meaning.  
3. **Granularity Adjustment - Less Detailed (1 variations):** Rewrite the query in a more generalized way by removing details while maintaining the overall meaning.  
4. **Query Expansion (1 variations):** Expand the query by adding relevant information to make it more comprehensive.  

The response must be returned in the following JSON format:
{{
"paraphrased_queries": [
    "Paraphrased query"
],
"detailed_queries": [
    "More detailed query"
],
"generalized_queries": [
    "More generalized query"
],
"expanded_queries": [
    "Expanded query"
]
}}
<|im_end|>

<|im_start|>user
Input Query:{query}  
<|im_end|> 
<|im_start|>assistant
"""

        query_transformation_prompt = PromptTemplate.from_template(query_transformation_template)

        # Chain
        query_transformation_generator = query_transformation_prompt | self.vllm_model| self.runnable
        return query_transformation_generator

    def get_query_transformation_generator(self):
        return self.query_transformation_generator
    
