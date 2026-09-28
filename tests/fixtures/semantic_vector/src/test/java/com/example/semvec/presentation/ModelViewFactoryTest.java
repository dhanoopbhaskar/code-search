package com.example.semvec.presentation;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

public final class ModelViewFactoryTest {

    @Test
    public void mapper_projectsModelToDto() {
        ModelViewFactory factory = new ModelViewFactory();
        ModelViewFactory.Dto dto = factory.mapper(new Model("{}"));
        assertEquals("{}", dto.json);
    }

    @Test
    public void project_producesOutputJson() {
        ModelViewFactory factory = new ModelViewFactory();
        ModelViewFactory.Output output = factory.project(new Model("{}"));
        assertEquals("{}", output.json);
    }
}