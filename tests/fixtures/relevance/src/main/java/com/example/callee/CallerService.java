package com.example.callee;

public class CallerService {
    public void orchestrate() {
        CalleeA helper = new CalleeA();
        String out = helper.transform("input");
        CalleeB worker = new CalleeB();
        worker.process("input", 42);
    }
}
