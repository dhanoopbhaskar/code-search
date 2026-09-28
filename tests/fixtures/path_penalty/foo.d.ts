export interface FooConfig {
  enabled: boolean;
  retries: number;
}

export declare function foo(config: FooConfig): void;
