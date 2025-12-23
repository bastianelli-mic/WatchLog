package it.michele.watchlog.model;

import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;
import lombok.ToString;

@Entity
@Data
@AllArgsConstructor
@NoArgsConstructor
@ToString
public class Film {

    @jakarta.persistence.Id
    @GeneratedValue(
            strategy = GenerationType.SEQUENCE,
            generator = "hibernate_sequence"
    )
    @SequenceGenerator(
            name = "hibernate_sequence",
            allocationSize = 1
    )
    @org.eclipse.microprofile.graphql.Id
    private Long id;
    private String title;

    public Film(String title) {
        this.title = title;
    }
}
