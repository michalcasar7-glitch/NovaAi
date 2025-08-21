package com.example.dispecink.service;

import com.example.dispecink.model.ChatMessage;
import com.google.cloud.vertexai.VertexAI;
import com.google.cloud.vertexai.api.GenerationConfig;
import com.google.cloud.vertexai.api.HarmCategory;
import com.google.cloud.vertexai.api.SafetySetting;
import com.google.cloud.vertexai.generativeai.ContentMaker;
import com.google.cloud.vertexai.generativeai.GenerativeModel;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.awt.Robot;
import java.io.IOException;
import java.util.Arrays;
import java.util.List;

@Service
public class ChatService {

    @Autowired
    private MongoTemplate mongoTemplate;

    @Autowired
    private SimpMessagingTemplate messagingTemplate;

    @Value("${vertex.ai.projectId}")
    private String projectId;

    @Value("${vertex.ai.location}")
    private String location;

    private String currentMode = "optimal";  // Výchozí režim AKP

    public ChatMessage processMessage(ChatMessage message) {
        // Uložit do MongoDB (historie chatu)
        mongoTemplate.insert(message, "chat_history");

        // Podle režimu AKP
        switch (currentMode) {
            case "optimal":
                // Asynchronní: Notifikace přes change streams (nastavte listener v init)
                // Pro jednoduchost: Broadcast přímo
                messagingTemplate.convertAndSend("/topic/notifications", "New message: " + message.getContent());
                break;
            case "proxy":
                // Proxy: Přímé řízení, uložení do Mongo a zobrazení
                messagingTemplate.convertAndSendToUser(message.getRecipient(), "/queue/private", message);
                break;
            case "reevaluate":
                // Orchestrace: Přepnutí režimu
                currentMode = "optimal";
                messagingTemplate.convertAndSend("/topic/system", "Switched to Optimal Mode");
                break;
        }

        // Integrace Gemini: Generovat odpověď pokud je to AI zpráva
        if (message.getSender().equals("AI")) {
            try {
                message.setContent(generateGeminiResponse(message.getContent()));
            } catch (IOException e) {
                // Handle error
            }
        }

        // Rozšíření o virtuální input (pokud message obsahuje command)
        if (message.getContent().contains("simulate_input")) {
            try {
                simulateInput("mouse", "moveTo(100,100)");  // Příklad – parsujte z message
            } catch (Exception e) {
                // Error
            }
        }

        return message;
    }

    public void processPrivateMessage(ChatMessage message) {
        // Pro proxy režim: Přímé odeslání
        messagingTemplate.convertAndSendToUser(message.getRecipient(), "/queue/private", message);
    }

    private String generateGeminiResponse(String prompt) throws IOException {
        try (VertexAI vertexAi = new VertexAI(projectId, location)) {
            GenerationConfig generationConfig = GenerationConfig.newBuilder()
                    .setMaxOutputTokens(8192)
                    .setTemperature(1F)
                    .setTopP(0.95F)
                    .build();
            List<SafetySetting> safetySettings = Arrays.asList(
                    SafetySetting.newBuilder().setCategory(HarmCategory.HARM_CATEGORY_HATE_SPEECH)
                            .setThreshold(SafetySetting.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE).build()
                    // ... další safety settings
            );
            GenerativeModel model = new GenerativeModel.Builder()
                    .setModelName("gemini-1.5-flash-001")
                    .setVertexAi(vertexAi)
                    .setGenerationConfig(generationConfig)
                    .setSafetySettings(safetySettings)
                    .build();

            var content = ContentMaker.fromMultiModalData(prompt);
            var response = model.generateContent(content);
            return response.toString();  // Extrahujte text z odpovědi
        }
    }

    // Příklad Change Stream pro notifikace (Optimální režim)
    public void initChangeStream() {
        // Spusťte v @PostConstruct: Sledujte změny v chat_history a notifikujte
        mongoTemplate.getCollection("chat_history").watch().forEach(change -> {
            // Notifikovat přes WebSocket
            messagingTemplate.convertAndSend("/topic/notifications", "Change detected: " + change.toString());
        });
    }

    // Alarm handling: Přepnutí do proxy při timeoutu (voláno z WebSocket handleru)
    public void handleAlarm(String agentId) {
        currentMode = "proxy";
        // ... Logika pro převzetí kontroly
    }

    // Virtuální input (rozšíření)
    public void simulateInput(String type, String action) throws Exception {
        Robot robot = new Robot();
        if (type.equals("mouse")) {
            // Parsujte action, např. robot.mouseMove(100, 100);
            String[] coords = action.split(",");
            robot.mouseMove(Integer.parseInt(coords[0]), Integer.parseInt(coords[1]));
        } else if (type.equals("keyboard")) {
            // robot.keyPress(KeyEvent.VK_A);
            robot.keyPress(Integer.parseInt(action));
        }
    }
}