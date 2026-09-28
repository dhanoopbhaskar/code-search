export class StateManager {
  private history: unknown[] = [];

  public push(entry: unknown): void {
    this.history.push(entry);
  }

  public undo(): void {
    this.history.pop();
  }
}
