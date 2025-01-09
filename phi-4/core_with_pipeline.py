import logging
import os
from dotenv import load_dotenv
import yaml
from itertools import product
from transformers import AutoTokenizer, AutoModelForCausalLM
from transformers import BitsAndBytesConfig
import bitsandbytes

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load the Hugging Face token
HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise EnvironmentError("Hugging Face token is not set in the environment variables.")

# Load prompts from config.yml
def load_prompts(config_path="phi-4/config.yml"):
    try:
        with open(config_path, "r") as file:
            config = yaml.safe_load(file)
            return config
    except FileNotFoundError:
        logger.error(f"Configuration file '{config_path}' not found.")
        raise
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        raise

prompts = load_prompts()
SYSTEM_PROMPT = prompts["system_prompt"]
FABLE_PROMPT = prompts["fable_prompt"]

# Load the GPT-Neo 125M model and tokenizer
model_name = "EleutherAI/gpt-neo-125M"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(model_name)

# Ensure the padding token is set
if tokenizer.pad_token is None:
    tokenizer.pad_token = tokenizer.eos_token

def generate_fable(character, trait, setting, conflict, resolution, moral):
    """
    Generates a fable using the PHI-4 model based on structured input.

    Args:
        character (str): The main character of the fable.
        trait (str): The trait of the character.
        setting (str): The setting of the fable.
        conflict (str): The central conflict in the story.
        resolution (str): How the conflict was resolved.
        moral (str): The moral of the fable.

    Returns:
        str: The generated fable.
    """
    structured_input = (
        f"Character: {character}\n"
        f"Trait: {trait}\n"
        f"Setting: {setting}\n"
        f"Conflict: {conflict}\n"
        f"Resolution: {resolution}\n"
        f"Moral: {moral}"
    )

    user_prompt = f"{FABLE_PROMPT}\n{structured_input}"
    inputs = tokenizer(user_prompt, return_tensors="pt", padding=True, truncation=True)

    logger.info("Generating fable with the model.")
    outputs = model.generate(**inputs, max_length=300, num_return_sequences=1)
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    return generated_text

if __name__ == "__main__":
    characters = ['Rabbit', 'Fox', 'Squirrel']
    traits = ['Brave', 'Greedy']
    settings = ['Forest', 'River']
    conflicts = ['Competing for food', 'Helping someone in need']
    resolutions = ['Reward', 'Punishment']
    morals = ['Kindness is rewarded', 'Hard work pays off']

    # Generate all combinations of fables
    fables = list(product(characters, traits, settings, conflicts, resolutions, morals))

    for fable in fables:
        character, trait, setting, conflict, resolution, moral = fable
        generated_fable = generate_fable(character, trait, setting, conflict, resolution, moral)
        print(f"\nGenerated Fable:\n{generated_fable}")
