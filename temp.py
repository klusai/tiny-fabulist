import time
import yaml
from pybars import Compiler
from itertools import product
import logging
from typing import List, Tuple, Dict, Any, Iterator
from random import sample
from decouple import config
import argparse
import json
import sys
from openai import OpenAI
import csv
import threading
from concurrent.futures import ThreadPoolExecutor  # Import ThreadPoolExecutor


# Constants
CONFIG_FILE = 'tinyfabulist.yaml'
LOG_FILE = 'tinyfabulist.log'
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

class TinyFabulistError(Exception):
    """Base exception for TinyFabulist errors"""
    pass

class ConfigError(TinyFabulistError):
    """Raised when there are configuration related errors"""
    pass

def setup_logging() -> logging.Logger:
    """Configure logging for the application
    
    Returns:
        logging.Logger: Configured logger instance
    """
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_FILE)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def load_settings() -> Dict[str, Any]:
    """Load settings from YAML file
    
    Returns:
        Dict[str, Any]: Configuration dictionary
        
    Raises:
        ConfigError: If config file is missing or invalid
    """
    try:
        with open(CONFIG_FILE, 'r') as file:
            settings = yaml.safe_load(file)
            logger.info("Settings loaded successfully")
            return settings
    except FileNotFoundError:
        logger.error(f"Settings file '{CONFIG_FILE}' not found")
        raise ConfigError(f"Settings file '{CONFIG_FILE}' not found")
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        raise ConfigError(f"Invalid YAML format: {e}")

def compile_template(prompt_fable: str) -> Any:
    """Compile the handlebars template
    
    Args:
        prompt_fable: The fable template string
        
    Returns:
        Any: Compiled template
        
    Raises:
        ConfigError: If template compilation fails
    """
    try:
        compiler = Compiler()
        template = compiler.compile(prompt_fable)
        logger.debug("Fable template compiled successfully")
        return template
    except Exception as e:
        logger.error(f"Failed to compile template: {e}")
        raise ConfigError(f"Template compilation failed: {e}")

def sample_features(features: Dict[str, List[str]], buffer_size: int, randomize: bool) -> Dict[str, List[str]]:
    """Sample features for prompt generation
    
    Args:
        features: Dictionary of feature lists
        buffer_size: Number of items to sample
        randomize: Whether to randomize the selection
        
    Returns:
        Dict[str, List[str]]: Sampled features
    """
    if randomize:
        return {
            key: sample(value, buffer_size)
            for key, value in features.items()
        }
    return {
        key: value[:buffer_size]
        for key, value in features.items()
    }

def generate_prompts(config: Dict[str, Any], count: int = 10, randomize: bool = False):
    """Generate story prompts from configuration
    
    Args:
        config: Configuration dictionary
        count: Number of prompts to generate
        randomize: Whether to randomize the selection
    """
    features = config['generator']['features']
    prompts = []
    used_combinations = set()  # Track combinations to avoid duplicates
    
    compiler = Compiler()
    # Fix: access templates from generator.prompt
    system_template = compiler.compile(config['generator']['prompt']['system'])
    generator_template = compiler.compile(config['generator']['prompt']['fable'])
    system_prompt = system_template({})
    
    while len(prompts) < count:
        if randomize:
            # Randomly select one item from each feature list
            combination = (
                sample(features['characters'], 1)[0],
                sample(features['traits'], 1)[0],
                sample(features['settings'], 1)[0],
                sample(features['conflicts'], 1)[0],
                sample(features['resolutions'], 1)[0],
                sample(features['morals'], 1)[0]
            )
            
            # Only add if this combination hasn't been used
            if combination not in used_combinations:
                used_combinations.add(combination)
                char, trait, setting, conflict, resolution, moral = combination
                context = {
                    'character': char,
                    'trait': trait,
                    'setting': setting,
                    'conflict': conflict,
                    'resolution': resolution,
                    'moral': moral
                }
                prompts.append(generator_template(context))
        else:
            # Non-random sequential selection
            idx = len(prompts)
            char = features['characters'][idx % len(features['characters'])]
            trait = features['traits'][idx % len(features['traits'])]
            setting = features['settings'][idx % len(features['settings'])]
            conflict = features['conflicts'][idx % len(features['conflicts'])]
            resolution = features['resolutions'][idx % len(features['resolutions'])]
            moral = features['morals'][idx % len(features['morals'])]
            
            context = {
                'trait': trait,
                'character': char,
                'setting': setting,
                'conflict': conflict,
                'resolution': resolution,
                'moral': moral
            }
            prompts.append(generator_template(context))
    
    return system_prompt, prompts

def parse_args() -> argparse.Namespace:
    """Parse command line arguments
    
    Returns:
        argparse.Namespace: Parsed command line arguments
    """
    parser = argparse.ArgumentParser(description='TinyFabulist - A fable prompt generator')
    parser.add_argument('--generate-prompts', action='store_true',
                      help='Generate fable prompts')
    parser.add_argument('--generate-fables', type=str,
                      help='Generate fables from a JSONL prompt file')
    parser.add_argument('--randomize', action='store_true',
                      help='Randomize feature selection')
    parser.add_argument('--output', choices=['text', 'jsonl', 'csv'],
                      default='text', help='Output format (default: text)')
    parser.add_argument('--count', type=int, default=100,
                      help='Number of prompts to generate (default: 100)')
    parser.add_argument('--models', nargs='+',
                      help='Specify models to use')
    parser.add_argument('--evaluate', type=str,
                      help='Evaluate fables from a JSONL file')
    return parser.parse_args()

def read_prompts(filename: str) -> Iterator[Dict[str, Any]]:
    """Read prompts from a JSONL file
    
    Args:
        filename: Path to JSONL file
        
    Yields:
        Dict[str, Any]: Prompt data
    """
    try:
        with open(filename, 'r') as f:
            for line in f:
                if line.strip():  # Skip empty lines
                    data = json.loads(line)
                    yield data
    except FileNotFoundError:
        logger.error(f"Prompt file '{filename}' not found")
        raise ConfigError(f"Prompt file '{filename}' not found")
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing JSONL file: {e}")
        raise ConfigError(f"Invalid JSONL format: {e}")

def generate_fable(system_prompt: str, fable_prompt: str, base_url: str) -> str:
    """Generate a fable using OpenAI
    
    Args:
        system_prompt: The system prompt
        fable_prompt: The fable prompt
        
    Returns:
        str: Generated fable
    """
    try:
        client = OpenAI(
            base_url=base_url,
            api_key=config('HF_ACCESS_TOKEN')
        )
        
        chat_completion = client.chat.completions.create(
            model="tgi",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": fable_prompt}
            ],
            max_tokens=1000,
            temperature=0.7,
            stream=True
        )

        fable_text = ""
        for message in chat_completion:
            if message.choices[0].delta.content is not None:
                fable_text += message.choices[0].delta.content
        return fable_text
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return f"Error generating fable: {e}"

def write_fables(fables: List[Dict[str, str]], output_format: str = 'text') -> None:
    """Write generated fables to stdout
    
    Args:
        fables: List of fable data including model, prompt and generated text
        output_format: Output format ('text', 'csv', or 'jsonl')
    """
    fields = ['model', 'prompt', 'fable']
    
    if output_format == 'csv':
        writer = csv.DictWriter(sys.stdout, fieldnames=fields)
        writer.writeheader()
        writer.writerows(fables)
    elif output_format == 'jsonl':
        for fable in fables:
            output = {field: fable[field] for field in fields}
            json.dump(output, sys.stdout)
            sys.stdout.write('\n')
    else:
        for fable in fables:
            print(f"\nModel: {fable['model']}")
            print(f"\nPrompt:\n{fable['prompt']}")
            print(f"\nFable:\n{fable['fable']}\n") 
            print("-" * 80)

def write_output(system_prompt: str, fable_templates: List[str], output_format: str) -> None:
    """Write output in the specified format
    
    Args:
        system_prompt: The system prompt
        fable_templates: List of generated fable templates
        output_format: Output format ('text' or 'jsonl')
    """
    if output_format == 'jsonl':        
        # Write each fable template and system prompt
        for template in fable_templates:
            json.dump([
                {
                    'prompt_type': 'system_prompt',
                    'content': system_prompt
                },
                {
                    'prompt_type': 'generator_prompt',
                    'content': template
                }
            ], sys.stdout)
            sys.stdout.write('\n')
    else:
        print("System prompt:", system_prompt)
        print("\nFable templates:")
        for i, template in enumerate(fable_templates, 1):
            print(f"\n{i}. {template}")


def generate_fable_threaded(model_name: str, model_config: Dict[str, Any], prompt: str, system_prompt: str, all_fables: List[Dict[str, str]], lock: threading.Lock) -> None:
    """
    Generates a fable in a separate thread.

    Args:
        model_name: The name of the model being used.
        model_config: The configuration for the model.
        prompt: The fable prompt.
        system_prompt: The system prompt.
        all_fables: A list to store the generated fables.
        lock: A thread lock to protect access to the shared list.
    """
    try:
        fable = generate_fable(
            system_prompt=system_prompt,
            fable_prompt=prompt,
            base_url=model_config['base_url']
        )
        with lock:
            all_fables.append({
                'model': model_config['name'],
                'prompt': prompt,
                'fable': fable
            })
        logger.info(f"Generated fable for prompt: {prompt[:50]}... using model {model_name}")
    except Exception as e:
        logger.error(f"Error generating fable in thread: {e}")

def evaluate_fable(fable: str) -> str:
    """Evaluate a fable using OpenAI's GPT model and returns a grade out of 10.
    
    Args:
        fable: The fable text to evaluate.
        
    Returns:
        str: The evaluation result from OpenAI.
    """
    try:
        client = OpenAI(api_key=config('OPENAI_TOKEN'))  # Use default base URL

        evaluation_prompt = f"""
        Please evaluate the following fable based on its creativity, coherence, 
        and moral lesson. Provide a grade from 1 to 10 (inclusive), where 1 is very poor and 10 is excellent.
        Respond with the grade only.

        Fable:
        {fable}
        """

        chat_completion = client.chat.completions.create(
            model="gpt-3.5-turbo",  # Or another suitable GPT model
            messages=[
                {"role": "system", "content": "You are a fable critic providing grades."},
                {"role": "user", "content": evaluation_prompt}
            ],
            max_tokens=10,
            temperature=0.0 # Set temperature to 0 to get deterministic results
        )

        evaluation_text = chat_completion.choices[0].message.content.strip()
        return evaluation_text
    except Exception as e:
        logger.error(f"OpenAI API error during evaluation: {e}")
        return f"Error evaluating fable: {e}"

def main() -> None:
    """Main entry point for the script"""
    args = parse_args()

    start_time = time.time()

    try:
        if args.generate_prompts:
            settings = load_settings()
            system_prompt, fable_templates = generate_prompts(
                settings,
                count=args.count,
                randomize=args.randomize
            )
            write_output(system_prompt, fable_templates, args.output)
        elif args.generate_fables:
            settings = load_settings()

            # Get available models from settings
            available_models = settings.get('llms', {}).get('hf-models', {})
            if not available_models:
                raise ConfigError("No models found in configuration")

            # If no models specified, use all available
            models_to_use = args.models if args.models else list(available_models.keys())

            # Validate requested models
            invalid_models = [m for m in models_to_use if m not in available_models]
            if invalid_models:
                raise ConfigError(f"Invalid models: {', '.join(invalid_models)}")

            # Read and process prompts
            prompts = list(read_prompts(args.generate_fables))
            system_prompt = next((p['content'] for p in prompts if p['prompt_type'] == 'system_prompt'), None)
            fable_prompts = [p['content'] for p in prompts if p['prompt_type'] == 'generator_prompt']

            if not system_prompt:
                raise ConfigError("No system prompt found in prompt file.")

            # Generate fables for each model
            all_fables = []
            threads = []
            lock = threading.Lock()  # Create a lock for thread-safe access to all_fables

            for model_name in models_to_use:
                model_config = available_models[model_name]
                logger.info(f"Generating fables using model: {model_config['name']}")

                for prompt in fable_prompts:
                    # Create a new thread for each fable generation
                    thread = threading.Thread(target=generate_fable_threaded,
                                              args=(model_name, model_config, prompt, system_prompt, all_fables, lock))
                    threads.append(thread)
                    thread.start()

            # Wait for all threads to complete
            for thread in threads:
                thread.join()

            write_fables(all_fables, args.output)
            
            end_time = time.time()  # Record end time
            elapsed_time = end_time - start_time
            logger.info(f"Fable generation completed in {elapsed_time:.2f} seconds")  # Log elapsed time
        elif args.evaluate:
            # Read fables from the specified JSONL file
            fables_to_evaluate = list(read_prompts(args.evaluate))

            # Evaluate each fable
            for fable_data in fables_to_evaluate:
                if 'fable' in fable_data:
                    fable_text = fable_data['fable']
                    evaluation = evaluate_fable(fable_text)
                    logger.info(f"Fable Evaluation:\n{evaluation}")
                    print(f"Fable:\n{fable_text}\nEvaluation:\n{evaluation}/10\n{'-'*80}")
                else:
                    logger.warning(f"Skipping entry due to missing 'fable' key: {fable_data}")

        else:
            logger.error("No action specified. Use --generate-prompts or --generate-fables")
            sys.exit(1)

    except TinyFabulistError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
if __name__ == "__main__":
    main()