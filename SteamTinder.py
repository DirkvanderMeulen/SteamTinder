import tkinter as tk
from tkinter import messagebox, filedialog
import csv
import json
import os
import atexit
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class SteamGameVoter:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Steam Game Voting UI")
        self.root.geometry("400x300")
        self.entries = []
        self.results = {}
        self.current_index = 0
        self.fieldnames = []
        self.driver = None
        self.input_filename = ""
        self.process_completed = False

    def read_file(self, filename):
        self.input_filename = os.path.splitext(os.path.basename(filename))[0]
        with open(filename, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            self.entries = list(reader)
            self.fieldnames = reader.fieldnames

    def initialize_voter():
        voter = SteamGameVoter()
        atexit.register(voter.save_progress)
        return voter

    def initialize_browser(self):
        browser_choice = self.browser_var.get()
        if browser_choice == "Chrome":
            options = ChromeOptions()
            self.driver = webdriver.Chrome(options=options)
        elif browser_choice == "Firefox":
            options = FirefoxOptions()
            self.driver = webdriver.Firefox(options=options)
        elif browser_choice == "Edge":
            options = EdgeOptions()
            self.driver = webdriver.Edge(options=options)
        self.driver.maximize_window()

    def open_webpage(self, url):
        if self.driver is None:
            self.initialize_browser()
        self.driver.get(url)
        # Wait for the page to load
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

    def vote(self, value):
        self.results[self.current_index] = value
        self.current_index += 1
        if self.current_index < len(self.entries):
            self.update_ui()
        else:
            self.show_results()

    def update_ui(self):
        entry = self.entries[self.current_index]
        self.entry_label.config(text=f"Game: {entry['name']}\nDeveloper: {entry['developers']}\nRelease Date: {entry['release_date']}")
        self.progress_label.config(text=f"Progress: {self.current_index + 1}/{len(self.entries)}")
        self.open_webpage(entry['steam_page_url'])

    def show_results(self):
        if self.driver:
            self.driver.quit()
        self.root.destroy()
        result_str = "\n".join([f"{self.entries[index]['name']}: {'Yes' if vote else 'No'}" for index, vote in self.results.items()])
        messagebox.showinfo("Voting Results", result_str)
        self.save_results()
        self.process_completed = True
        self.delete_progress_file()

    def delete_progress_file(self):
        if os.path.exists('progress.json'):
            os.remove('progress.json')
            print("Progress file deleted.")

    def save_results(self):
        yes_votes = [self.entries[i] for i, vote in self.results.items() if vote]
        no_votes = [self.entries[i] for i, vote in self.results.items() if not vote]

        data_folder = 'data'
        os.makedirs(data_folder, exist_ok=True)

        yes_filename = f"{self.input_filename}_yes_votes.csv"
        no_filename = f"{self.input_filename}_no_votes.csv"
        
        self.save_csv(os.path.join(data_folder, yes_filename), yes_votes)
        self.save_csv(os.path.join(data_folder, no_filename), no_votes)

        messagebox.showinfo("Results Saved", f"Results have been saved to 'yes_votes.csv' and 'no_votes.csv' in {os.path.abspath(data_folder)}")

    def save_csv(self, filename, data):
        with open(filename, 'w', newline='', encoding='utf-8') as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            writer.writerows(data)

    def save_progress(self):
        if self.process_completed:
            return
        progress = {
            'current_index': self.current_index,
            'results': self.results
        }
        with open('progress.json', 'w') as f:
            json.dump(progress, f)
        messagebox.showinfo("Progress Saved", "Progress has been saved.")

    def load_progress(self):
        if os.path.exists('progress.json'):
            with open('progress.json', 'r') as f:
                progress = json.load(f)
            self.current_index = progress['current_index']
            self.results = {int(k): v for k, v in progress['results'].items()}
            messagebox.showinfo("Progress Loaded", "Progress has been loaded.")
            return True
        return False

    def create_ui(self):
        self.entry_label = tk.Label(self.root, text="", wraplength=380, justify="center")
        self.entry_label.pack(pady=10)

        self.progress_label = tk.Label(self.root, text="")
        self.progress_label.pack(pady=5)

        button_frame = tk.Frame(self.root)
        button_frame.pack(pady=10)

        yes_button = tk.Button(button_frame, text="Yes", command=lambda: self.vote(True), width=10)
        yes_button.pack(side=tk.LEFT, padx=10)

        no_button = tk.Button(button_frame, text="No", command=lambda: self.vote(False), width=10)
        no_button.pack(side=tk.RIGHT, padx=10)

        save_button = tk.Button(self.root, text="Save Progress", command=self.save_progress, width=15)
        save_button.pack(pady=5)

        self.browser_var = tk.StringVar(value="Chrome")
        browser_frame = tk.Frame(self.root)
        browser_frame.pack(pady=5)
        tk.Label(browser_frame, text="Browser:").pack(side=tk.LEFT)
        tk.Radiobutton(browser_frame, text="Chrome", variable=self.browser_var, value="Chrome").pack(side=tk.LEFT)
        tk.Radiobutton(browser_frame, text="Firefox", variable=self.browser_var, value="Firefox").pack(side=tk.LEFT)
        tk.Radiobutton(browser_frame, text="Edge", variable=self.browser_var, value="Edge").pack(side=tk.LEFT)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if file_path:
            self.read_file(file_path)
            if self.entries:
                self.create_ui()
                if not self.load_progress():
                    self.current_index = 0
                self.update_ui()
                self.root.mainloop()
            else:
                messagebox.showerror("Error", "No entries found in the selected file.")
        else:
            messagebox.showinfo("Info", "No file selected. Exiting.")

# Main program


if __name__ == "__main__":
    try:
        voter = SteamGameVoter.initialize_voter()
        voter.select_file()
    except Exception as e:
        print(f"An error occurred: {e}")
        # This will trigger the atexit function to save progress