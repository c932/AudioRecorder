import json
import os

class ExerciseManager:
    def __init__(self, data_file):
        self.data_file = data_file
        self.exercises = self.load_data()
        print(f"[DEBUG] ExerciseManager {id(self)} initialized. Data file: {data_file}")
        
    def load_data(self):
        if not os.path.exists(self.data_file):
            return {"words": [], "sentences": []}
        with open(self.data_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_data(self):
        print(f"[DEBUG] ExerciseManager {id(self)} saving data to {self.data_file}...")
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(self.exercises, f, indent=4, ensure_ascii=False)
        print(f"[DEBUG] ExerciseManager {id(self)} saved.")

    def add_exercises(self, new_items, category="words"):
        if category not in self.exercises:
            self.exercises[category] = []
        
        # Avoid duplicates (Check by Text + Group)
        # We allow the same word to exist in different groups
        existing_keys = {(item['text'], item.get('group', 'Default')) for item in self.exercises[category]}
        
        count = 0
        for item in new_items:
            # item may not have group if old code? ImportDialog always injects it now.
            # Default to "Default" for robust comparison
            key = (item['text'], item.get('group', 'Default'))
            
            if key not in existing_keys:
                self.exercises[category].append(item)
                existing_keys.add(key) # Add to set to prevent duplicates within the *same* new batch
                count += 1
                
        self.save_data()
        return count

    def clear_all_exercises(self):
        """Clears all exercises and saves the empty state."""
        self.exercises = {"words": [], "sentences": []}
        self.save_data()
        return True

    def get_groups(self):
        """Returns a list of unique group names found in the data."""
        groups = set()
        for category in self.exercises:
            for item in self.exercises[category]:
                groups.add(item.get('group', 'Default'))
        return sorted(list(groups))

    def delete_group(self, group_name):
        """Deletes all items belonging to the specified group."""
        changed = False
        for category in self.exercises:
            original_len = len(self.exercises[category])
            # Keep items that DO NOT match the group
            self.exercises[category] = [i for i in self.exercises[category] if i.get('group', 'Default') != group_name]
            if len(self.exercises[category]) != original_len:
                changed = True
        
        if changed:
            self.save_data()
        return changed

    def reset_stats(self):
        """Resets progress stats (times_practiced, last_score) for ALL items."""
        count = 0
        for category in self.exercises:
            for item in self.exercises[category]:
                if 'times_practiced' in item:
                    del item['times_practiced']
                if 'last_score' in item:
                    del item['last_score']
                count += 1
        self.save_data()
        return count
